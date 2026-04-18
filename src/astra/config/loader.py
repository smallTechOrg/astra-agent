"""Load operator config from operator.yaml and tenant config from the database.

Per spec/product/05-config.md: operator.yaml holds operator-level settings;
tenant config, secrets, and cadences are stored in PostgreSQL. DATABASE_URL
is read from config/.env (or OS env).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml
from pydantic import SecretStr, ValidationError

from astra.config.models import OperatorConfig, TenantConfig
from astra.config.secrets import assert_no_secret_values, load_dotenv_file
from astra.errors import ConfigValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from astra.db.connection import Database

log = logging.getLogger(__name__)


@dataclass
class LoadedTenant:
    """A tenant as held in memory at runtime: config + resolved secrets + status."""

    config: TenantConfig
    secrets: dict[str, SecretStr] = field(default_factory=dict)
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass
class LoadedConfig:
    operator: OperatorConfig
    database_url: str


class ConfigLoader:
    """Loads operator config from files; tenant config from the database."""

    def __init__(self, config_dir: Path, *, os_env: dict[str, str] | None = None) -> None:
        self._config_dir = config_dir
        self._os_env: dict[str, str] = dict(os_env) if os_env is not None else dict(os.environ)

    def load(self) -> LoadedConfig:
        """Load operator.yaml and resolve DATABASE_URL. Synchronous — no DB access."""
        operator = self._load_operator()
        operator_env = load_dotenv_file(self._config_dir / ".env")
        database_url = (
            operator_env.get("DATABASE_URL")
            or self._os_env.get("DATABASE_URL")
            or ""
        )
        if not database_url:
            log.warning("DATABASE_URL not set — DB operations will fail at connection time")
        return LoadedConfig(operator=operator, database_url=database_url)

    async def load_tenants_from_db(self, db: Database) -> dict[str, LoadedTenant]:
        """Query the DB and return all tenants as LoadedTenant objects."""
        from astra.db.repos import (
            CadencesRepo,
            TenantConfigRepo,
            TenantSecretsRepo,
            TenantsRepo,
        )

        tenants_repo = TenantsRepo(db)
        config_repo = TenantConfigRepo(db)
        secrets_repo = TenantSecretsRepo(db)
        cadences_repo = CadencesRepo(db)

        loaded: dict[str, LoadedTenant] = {}
        rows = await tenants_repo.list_all()

        for row in rows:
            tenant_id: str = row["id"]
            try:
                db_cfg = await config_repo.get(tenant_id)
                if db_cfg is None:
                    log.error(
                        "tenant_config_missing",
                        extra={"tenant_id": tenant_id},
                    )
                    loaded[tenant_id] = LoadedTenant(
                        config=TenantConfig(id=tenant_id, name=row["name"]),
                        degraded=True,
                        degraded_reason="tenant_config row missing",
                    )
                    continue

                cadence_records = await cadences_repo.list_for_tenant(tenant_id)
                config = TenantConfig.from_db(
                    tenant_id=tenant_id,
                    tenant_name=row["name"],
                    enabled=row["enabled"],
                    db_cfg=db_cfg,
                    cadence_records=cadence_records,
                )

                secret_keys = await secrets_repo.list_keys(tenant_id)
                secrets: dict[str, SecretStr] = {}
                for key in secret_keys:
                    value = await secrets_repo.get(tenant_id, key)
                    if value:
                        secrets[key] = SecretStr(value)

                loaded[tenant_id] = LoadedTenant(config=config, secrets=secrets)

            except Exception as exc:
                log.error(
                    "tenant_load_failed",
                    extra={"tenant_id": tenant_id, "error": str(exc)},
                )
                loaded[tenant_id] = LoadedTenant(
                    config=TenantConfig(id=tenant_id, name=str(row["name"])),
                    degraded=True,
                    degraded_reason=str(exc),
                )

        return loaded

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


__all__ = [
    "ConfigLoader",
    "LoadedConfig",
    "LoadedTenant",
]
