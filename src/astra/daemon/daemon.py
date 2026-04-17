"""AstraDaemon — loads tenants, wires APScheduler jobs, handles shutdown.

Per spec/product/02-architecture.md (process model) and
spec/product/03-tenancy.md (failure isolation).
"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astra.config.loader import ConfigLoader
from astra.daemon.runner import TenantRunner
from astra.db import Database, migrate
from astra.db.repos import TenantsRepo
from astra.llm.factory import build_llm_client
from astra.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

log = get_logger(__name__)


class AstraDaemon:
    """Single-process async daemon.

    One scheduler, one DB connection, one LLM client per tenant.
    Degraded tenants are registered but no jobs run for them.
    """

    def __init__(self, config_dir: Path, db_path: Path | None = None) -> None:
        self._config_dir = config_dir
        self._db_path = db_path
        self._scheduler = AsyncIOScheduler()
        self._db: Database | None = None
        self._runners: dict[str, TenantRunner] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Load config, open DB, schedule jobs, then block until shutdown."""
        cfg = ConfigLoader(self._config_dir).load()

        db_path = self._db_path or (self._config_dir.parent / cfg.operator.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = Database(db_path)
        await self._db.connect()
        await migrate(self._db)

        tenants_repo = TenantsRepo(self._db)

        enabled_count = 0
        job_count = 0

        for tenant_id, loaded in cfg.tenants.items():
            await tenants_repo.upsert(tenant_id, loaded.config.name, loaded.config.enabled)

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
                    api_key_env=loaded.config.llm.api_key_env or cfg.operator.llm.api_key_env,
                )

            api_key_env = llm_cfg.api_key_env
            api_key_secret = loaded.secrets.get(api_key_env)
            import os
            api_key = (
                api_key_secret.get_secret_value()
                if api_key_secret
                else os.environ.get(api_key_env, "")
            )

            llm = build_llm_client(llm_cfg, api_key=api_key)

            from astra.prompts.resolver import PromptResolver
            operator_prompts = self._config_dir.parent / "prompts"
            tenant_prompts = self._config_dir / "tenants" / tenant_id / "prompts"
            prompts = PromptResolver(
                operator_prompts_dir=operator_prompts,
                tenant_prompts_dir=tenant_prompts if tenant_prompts.exists() else None,
            )

            runner = TenantRunner(
                tenant=loaded.config,
                db=self._db,
                llm=llm,
                prompts=prompts,
                secrets=loaded.secrets,
            )
            self._runners[tenant_id] = runner

            # Schedule wp-poll job.
            self._scheduler.add_job(
                runner.poll_and_distribute,
                trigger="cron",
                id=f"{tenant_id}:wp-poll",
                **_parse_cron(loaded.config.source.poll_cron),
            )
            job_count += 1

            # Schedule share-sweep job.
            self._scheduler.add_job(
                runner.share_sweep,
                trigger="cron",
                id=f"{tenant_id}:share-sweep",
                **_parse_cron(cfg.operator.daemon.share_sweep_cron),
            )
            job_count += 1

            # Schedule per-cadence jobs.
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

        for error_tenant, error_msg in cfg.load_errors.items():
            log.error("tenant_load_failed", tenant_id=error_tenant, error=error_msg)

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
