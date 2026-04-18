"""AstraDaemon — loads tenants from DB, wires APScheduler jobs, handles shutdown.

Per spec/product/02-architecture.md (process model) and
spec/product/03-tenancy.md (failure isolation).
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astra.config.loader import ConfigLoader
from astra.daemon.runner import TenantRunner
from astra.db import Database, migrate
from astra.db.repos import DaemonHeartbeatRepo, PromptsRepo
from astra.llm.factory import build_llm_client
from astra.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

log = get_logger(__name__)

_VERSION = "0.2.0"


class AstraDaemon:
    """Single-process async daemon.

    One scheduler, one DB connection pool, one LLM client per tenant.
    Degraded tenants are registered but no jobs run for them.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._scheduler = AsyncIOScheduler()
        self._db: Database | None = None
        self._runners: dict[str, TenantRunner] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Load config, open DB pool, schedule jobs, then block until shutdown."""
        loader = ConfigLoader(self._config_dir)
        cfg = loader.load()

        if not cfg.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it to config/.env or the OS environment."
            )

        self._db = Database(cfg.database_url)
        await self._db.connect()
        await migrate(self._db)

        loaded_tenants = await loader.load_tenants_from_db(self._db)

        enabled_count = 0
        job_count = 0

        for tenant_id, loaded in loaded_tenants.items():
            if not loaded.config.enabled:
                log.info("tenant_skipped", tenant_id=tenant_id, reason="disabled")
                continue

            if loaded.degraded:
                log.warning(
                    "tenant_degraded",
                    tenant_id=tenant_id,
                    reason=loaded.degraded_reason,
                )
                continue

            enabled_count += 1
            llm_cfg = cfg.operator.llm
            if loaded.config.llm is not None:
                from astra.config.models import LLMConfig
                llm_cfg = LLMConfig(
                    provider=loaded.config.llm.provider or cfg.operator.llm.provider,
                    model=loaded.config.llm.model or cfg.operator.llm.model,
                    temperature=loaded.config.llm.temperature or cfg.operator.llm.temperature,
                    max_tokens=loaded.config.llm.max_tokens or cfg.operator.llm.max_tokens,
                    api_key_env=cfg.operator.llm.api_key_env,
                )

            import os
            api_key = os.environ.get(llm_cfg.api_key_env, "")
            llm = build_llm_client(llm_cfg, api_key=api_key)

            from astra.prompts.resolver import PromptResolver
            prompts = PromptResolver(db=self._db, tenant_id=tenant_id)

            # Per spec/product/08-prompts.md: daemon must fail to start for
            # a tenant if any required prompt is missing from the DB.
            required_prompts: list[str] = []
            if loaded.config.destinations.linkedin.enabled:
                required_prompts.append(loaded.config.destinations.linkedin.prompt)
            if loaded.config.destinations.twitter.enabled:
                required_prompts.append(
                    loaded.config.destinations.twitter.announcement_prompt
                )
            for cadence_cfg in loaded.config.cadences:
                if cadence_cfg.enabled:
                    required_prompts.append(cadence_cfg.prompt)

            prompts_repo = PromptsRepo(self._db)
            missing: list[str] = []
            for pname in required_prompts:
                record = await prompts_repo.resolve(tenant_id, pname)
                if record is None:
                    missing.append(pname)
            if missing:
                log.error(
                    "tenant_missing_prompts",
                    tenant_id=tenant_id,
                    missing=missing,
                )
                continue

            runner = TenantRunner(
                tenant=loaded.config,
                db=self._db,
                llm=llm,
                prompts=prompts,
                secrets=loaded.secrets,
            )
            self._runners[tenant_id] = runner

            self._scheduler.add_job(
                runner.poll_and_distribute,
                trigger="cron",
                id=f"{tenant_id}:wp-poll",
                **_parse_cron(loaded.config.source.poll_cron),
            )
            job_count += 1

            self._scheduler.add_job(
                runner.share_sweep,
                trigger="cron",
                id=f"{tenant_id}:share-sweep",
                **_parse_cron(cfg.operator.daemon.share_sweep_cron),
            )
            job_count += 1

            for cadence_cfg in loaded.config.cadences:
                if not cadence_cfg.enabled:
                    continue
                self._scheduler.add_job(
                    runner.cadence_tick,
                    trigger="cron",
                    id=f"{tenant_id}:cadence:{cadence_cfg.name}",
                    args=[cadence_cfg],
                    **_parse_cron(cadence_cfg.cron),
                )
                job_count += 1

        await DaemonHeartbeatRepo(self._db).upsert(
            started_at=datetime.now(UTC),
            version=_VERSION,
            tenant_count=enabled_count,
            job_count=job_count,
        )

        grace = cfg.operator.daemon.startup_grace_seconds
        if grace > 0:
            log.info("startup_grace", seconds=grace)
            await asyncio.sleep(grace)

        self._scheduler.start()

        log.info(
            "astra_daemon_started",
            tenants_enabled=enabled_count,
            jobs_scheduled=job_count,
        )

        _install_signal_handlers(self._stop_event)

        await self._stop_event.wait()
        await self._shutdown()

    async def _shutdown(self) -> None:
        log.info("astra_daemon_stopping")
        self._scheduler.shutdown(wait=True)
        if self._db is not None:
            await self._db.close()
        log.info("astra_daemon_stopped")


def _parse_cron(expr: str) -> dict[str, str]:
    """Convert a 5-field cron expression to APScheduler CronTrigger kwargs."""
    minute, hour, day, month, day_of_week = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("astra_daemon_signal_received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)
