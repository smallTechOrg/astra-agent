"""Walk config/ and produce a validated, secret-resolved view.

Per spec/product/05-config.md. One tenant's failures never prevent another
tenant from loading — they are logged and the tenant is marked degraded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml
from croniter import croniter
from pydantic import SecretStr, ValidationError

from astra.config.models import OperatorConfig, TenantConfig
from astra.config.secrets import SecretResolver, assert_no_secret_values, load_dotenv_file
from astra.errors import (
    ConfigValidationError,
    CronParseError,
    DuplicateCadenceNameError,
    TenantIdMismatchError,
)

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class LoadedTenant:
    """A tenant as held in memory at runtime: config + resolved secrets + status."""

    config: TenantConfig
    secrets: dict[str, SecretStr]
    degraded: bool = False
    degraded_reason: str | None = None
    load_warnings: list[str] = field(default_factory=list)


@dataclass
class LoadedConfig:
    operator: OperatorConfig
    tenants: dict[str, LoadedTenant]
    load_errors: dict[str, str] = field(default_factory=dict)


class ConfigLoader:
    """Loads operator.yaml and every tenant under tenants/."""

    def __init__(self, config_dir: Path, *, os_env: dict[str, str] | None = None) -> None:
        self._config_dir = config_dir
        self._os_env = os_env

    def load(self) -> LoadedConfig:
        operator = self._load_operator()
        operator_env = load_dotenv_file(self._config_dir / ".env")

        tenants: dict[str, LoadedTenant] = {}
        load_errors: dict[str, str] = {}
        tenants_root = self._config_dir / "tenants"
        if not tenants_root.exists():
            return LoadedConfig(operator=operator, tenants=tenants, load_errors=load_errors)

        for tenant_dir in sorted(p for p in tenants_root.iterdir() if p.is_dir()):
            tenant_id = tenant_dir.name
            try:
                loaded = self._load_tenant(tenant_dir, operator_env=operator_env)
                tenants[loaded.config.id] = loaded
            except (
                TenantIdMismatchError,
                ConfigValidationError,
                DuplicateCadenceNameError,
                CronParseError,
            ) as exc:
                load_errors[tenant_id] = str(exc)
                log.error("tenant load failed", extra={"tenant_id": tenant_id, "error": str(exc)})

        return LoadedConfig(operator=operator, tenants=tenants, load_errors=load_errors)

    def _load_operator(self) -> OperatorConfig:
        path = self._config_dir / "operator.yaml"
        if not path.exists():
            return OperatorConfig()
        raw = yaml.safe_load(path.read_text()) or {}
        assert_no_secret_values(raw, path="operator.yaml")
        try:
            return OperatorConfig.model_validate(raw)
        except ValidationError as exc:
            raise ConfigValidationError(f"operator.yaml: {exc}") from exc

    def _load_tenant(self, tenant_dir: Path, *, operator_env: dict[str, str]) -> LoadedTenant:
        tenant_id_from_dir = tenant_dir.name
        yaml_path = tenant_dir / "tenant.yaml"
        if not yaml_path.exists():
            raise ConfigValidationError(
                f"tenant {tenant_id_from_dir!r}: tenant.yaml is missing"
            )

        raw = yaml.safe_load(yaml_path.read_text()) or {}
        assert_no_secret_values(raw, path=f"tenants/{tenant_id_from_dir}/tenant.yaml")

        warnings: list[str] = []
        if isinstance(raw, dict):
            warnings.extend(self._collect_unknown_key_warnings(raw))

        try:
            config = TenantConfig.model_validate(raw)
        except ValidationError as exc:
            raise ConfigValidationError(
                f"tenant {tenant_id_from_dir!r}: {exc}"
            ) from exc

        if config.id != tenant_id_from_dir:
            raise TenantIdMismatchError(
                f"tenant {tenant_id_from_dir!r}: id {config.id!r} in tenant.yaml "
                f"does not match directory name"
            )

        self._validate_cadences(config)
        self._validate_crons(config)

        tenant_env = load_dotenv_file(tenant_dir / ".env")
        resolver = SecretResolver(
            tenant_id=config.id,
            tenant_env=tenant_env,
            operator_env=operator_env,
            os_env=self._os_env,
        )
        secrets, missing = self._resolve_required_secrets(config, resolver)

        loaded = LoadedTenant(
            config=config,
            secrets=secrets,
            load_warnings=warnings,
        )
        if missing:
            loaded.degraded = True
            loaded.degraded_reason = (
                f"missing required secrets: {', '.join(sorted(missing))}"
            )
        return loaded

    def _collect_unknown_key_warnings(self, raw: dict[str, object]) -> list[str]:
        known_top = {"id", "name", "enabled", "source", "destinations", "cadences", "llm"}
        return [f"unknown top-level key {key!r} (ignored)" for key in raw if key not in known_top]

    def _validate_cadences(self, config: TenantConfig) -> None:
        names: set[str] = set()
        for cadence in config.cadences:
            if cadence.name in names:
                raise DuplicateCadenceNameError(
                    f"tenant {config.id!r}: duplicate cadence name {cadence.name!r}"
                )
            names.add(cadence.name)

    def _validate_crons(self, config: TenantConfig) -> None:
        self._check_cron(config.source.poll_cron, f"source.poll_cron for tenant {config.id!r}")
        for cadence in config.cadences:
            if not cadence.enabled:
                continue
            self._check_cron(
                cadence.cron,
                f"cadences[{cadence.name!r}].cron for tenant {config.id!r}",
            )

    def _check_cron(self, expr: str, where: str) -> None:
        if not croniter.is_valid(expr):
            raise CronParseError(f"{where}: invalid cron expression {expr!r}")

    def _resolve_required_secrets(
        self, config: TenantConfig, resolver: SecretResolver
    ) -> tuple[dict[str, SecretStr], set[str]]:
        required: dict[str, str] = {}
        required[config.source.app_password_env] = "source.app_password"

        if config.destinations.linkedin.enabled:
            required[config.destinations.linkedin.access_token_env] = "linkedin.access_token"

        if config.destinations.twitter.enabled:
            required[config.destinations.twitter.api_key_env] = "twitter.api_key"
            required[config.destinations.twitter.api_secret_env] = "twitter.api_secret"
            required[config.destinations.twitter.access_token_env] = "twitter.access_token"
            required[config.destinations.twitter.access_secret_env] = "twitter.access_secret"

        resolved: dict[str, SecretStr] = {}
        missing: set[str] = set()
        for env_var in required:
            value = resolver.resolve(env_var)
            if value is None:
                missing.add(env_var)
            else:
                resolved[env_var] = value
        return resolved, missing


__all__ = [
    "ConfigLoader",
    "LoadedConfig",
    "LoadedTenant",
]
