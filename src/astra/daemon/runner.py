"""TenantRunner — per-tenant poll, distribute, and cadence-tick orchestrator.

Per spec/product/02-architecture.md and spec/engineering/tenant-isolation.md (P3).
P3: a top-level except in TenantRunner logs but never re-raises — one tenant's
failure never halts another tenant's scheduled jobs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.daemon.distributor import distribute_event, sweep_pending
from astra.logging import get_logger
from astra.sources import get_source

if TYPE_CHECKING:
    import structlog
    from pydantic import SecretStr

    from astra.config.models import CadenceConfig, TenantConfig
    from astra.db.connection import Database
    from astra.llm.base import LLMClient
    from astra.prompts.resolver import PromptResolver

log = get_logger(__name__)


class TenantRunner:
    """Wraps all scheduled jobs for one tenant.

    Every public async method is safe to call from APScheduler: it catches
    all exceptions at the top level (P3) and logs them without re-raising.
    """

    def __init__(
        self,
        tenant: TenantConfig,
        db: Database,
        llm: LLMClient,
        prompts: PromptResolver,
        secrets: dict[str, SecretStr],
    ) -> None:
        self._tenant = tenant
        self._db = db
        self._llm = llm
        self._prompts = prompts
        self._secrets = secrets

    async def poll_and_distribute(self) -> None:
        """Source poll + immediate fan-out to all enabled destinations."""
        bound = log.bind(tenant_id=self._tenant.id, job="poll_and_distribute")
        try:
            await self._do_poll_and_distribute(bound)
        except Exception as exc:
            bound.error("tenant_runner_error", job="poll_and_distribute", error=str(exc))

    async def share_sweep(self) -> None:
        """Retry transient distribution failures from earlier ticks."""
        bound = log.bind(tenant_id=self._tenant.id, job="share_sweep")
        try:
            await sweep_pending(
                self._tenant, self._db, self._llm, self._prompts, self._secrets
            )
        except Exception as exc:
            bound.error("tenant_runner_error", job="share_sweep", error=str(exc))

    async def cadence_tick(self, cadence_cfg: CadenceConfig) -> None:
        """Execute one tick of the named cadence."""
        bound = log.bind(tenant_id=self._tenant.id, job=f"cadence:{cadence_cfg.name}")
        try:
            await self._do_cadence_tick(cadence_cfg, bound)
        except Exception as exc:
            bound.error(
                "tenant_runner_error",
                job=f"cadence:{cadence_cfg.name}",
                error=str(exc),
            )

    # ── internals ───────────────────────────────────────────────

    async def _do_poll_and_distribute(self, bound: structlog.stdlib.BoundLogger) -> None:
        source_cfg = self._tenant.source
        source_cls = get_source(source_cfg.type)
        source = source_cls()

        app_password_secret = self._secrets.get("WP_APP_PASSWORD")
        app_password = app_password_secret.get_secret_value() if app_password_secret else ""

        bound.info("poll_started")
        new_events = await source.poll(self._tenant, self._db, app_password=app_password)
        bound.info("poll_completed", new_events=len(new_events))

        for event in new_events:
            if event.db_id is None:
                continue
            await distribute_event(
                self._tenant,
                event.db_id,
                self._db,
                self._llm,
                self._prompts,
                self._secrets,
            )

    async def _do_cadence_tick(self, cadence_cfg: CadenceConfig, bound: structlog.stdlib.BoundLogger) -> None:
        from astra.cadences import get_cadence

        cadence_cls = get_cadence("twitter")  # v0.1: only Twitter cadences exist
        cadence = cadence_cls()

        access_token = _pack_twitter_token(self._secrets)

        result = await cadence.tick(
            self._tenant,
            cadence_cfg,
            self._db,
            self._llm,
            self._prompts,
            access_token=access_token,
        )
        bound.info("cadence_tick_completed", result=type(result).__name__)


def _pack_twitter_token(secrets: dict[str, SecretStr]) -> str:
    def _get(key: str) -> str:
        s = secrets.get(key)
        return s.get_secret_value() if s else ""

    return "|".join([
        _get("TWITTER_API_KEY"),
        _get("TWITTER_API_SECRET"),
        _get("TWITTER_ACCESS_TOKEN"),
        _get("TWITTER_ACCESS_SECRET"),
    ])
