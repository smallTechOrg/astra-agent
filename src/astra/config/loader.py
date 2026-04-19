"""Load operator config from DB and tenant config from the database.

Per spec/product/05-config.md: operator.yaml is eliminated. All operator
config lives in the operator_config DB table. DATABASE_URL is the only
setting read from config/.env (bootstrap secret).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import SecretStr

from astra.config.models import OperatorConfig, TenantConfig
from astra.config.secrets import load_dotenv_file

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
    """Loads bootstrap secrets from .env; operator and tenant config from the DB."""

    def __init__(self, config_dir: Path, *, os_env: dict[str, str] | None = None) -> None:
        self._config_dir = config_dir
        self._os_env: dict[str, str] = dict(os_env) if os_env is not None else dict(os.environ)

    def load_bootstrap(self) -> str:
        """Load DATABASE_URL from config/.env or OS env. Synchronous — no DB access."""
        operator_env = load_dotenv_file(self._config_dir / ".env")
        database_url = (
            operator_env.get("DATABASE_URL")
            or self._os_env.get("DATABASE_URL")
            or ""
        )
        if not database_url:
            log.warning("DATABASE_URL not set — DB operations will fail at connection time")
        return database_url

    def load_ui_password(self) -> str | None:
        """Load ASTRA_UI_PASSWORD from config/.env or OS env."""
        operator_env = load_dotenv_file(self._config_dir / ".env")
        return (
            operator_env.get("ASTRA_UI_PASSWORD")
            or self._os_env.get("ASTRA_UI_PASSWORD")
            or None
        )

    async def load_operator_from_db(self, db: Database) -> OperatorConfig:
        """Read operator_config from the DB and return an OperatorConfig model."""
        from astra.db.repos import OperatorConfigRepo

        repo = OperatorConfigRepo(db)
        record = await repo.get()
        if record is None:
            log.warning("operator_config row missing — using defaults")
            return OperatorConfig()
        return OperatorConfig.from_db(record)

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


__all__ = [
    "ConfigLoader",
    "LoadedConfig",
    "LoadedTenant",
]
