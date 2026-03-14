from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astra.core.engine import AstraEngine
from astra.wordpress.models import ContentBrief

logger = structlog.get_logger(__name__)


def _parse_cron(expression: str) -> CronTrigger:
    """Parse a standard 5-field cron expression into an APScheduler ``CronTrigger``.

    Expected format: ``minute hour day month day_of_week``
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        msg = f"Expected a 5-field cron expression, got {len(parts)} fields: {expression!r}"
        raise ValueError(msg)

    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


class AstraScheduler:
    """Task scheduler for recurring Astra content and distribution jobs.

    Wraps APScheduler's ``AsyncIOScheduler`` to provide a simple interface
    for scheduling content generation, social media distribution, and
    Twitter bot engagement jobs.

    Usage::

        scheduler = AstraScheduler(engine)
        scheduler.add_content_job("0 9 * * 1", brief)
        scheduler.add_distribution_job("0 */6 * * *")
        scheduler.start()
    """

    def __init__(self, engine: AstraEngine) -> None:
        self._engine = engine
        self._scheduler = AsyncIOScheduler()
        self._log = logger.bind(component="scheduler")
        self._job_counter = 0

    # ── Job registration ─────────────────────────────────────────

    def add_content_job(self, cron_expr: str, brief: ContentBrief) -> str:
        """Schedule recurring content generation."""
        trigger = _parse_cron(cron_expr)
        self._job_counter += 1
        job_id = f"content_{self._job_counter}"

        self._scheduler.add_job(
            self._run_content_job,
            trigger=trigger,
            id=job_id,
            kwargs={"brief": brief},
            replace_existing=True,
        )
        self._log.info("content_job_added", job_id=job_id, cron=cron_expr, topic=brief.topic)
        return job_id

    def add_distribution_job(self, cron_expr: str) -> str:
        """Schedule recurring social media distribution."""
        trigger = _parse_cron(cron_expr)
        self._job_counter += 1
        job_id = f"distribution_{self._job_counter}"

        self._scheduler.add_job(
            self._run_distribution_job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
        )
        self._log.info("distribution_job_added", job_id=job_id, cron=cron_expr)
        return job_id

    def add_engagement_job(self, cron_expr: str) -> str:
        """Schedule recurring Twitter bot engagement."""
        trigger = _parse_cron(cron_expr)
        self._job_counter += 1
        job_id = f"engagement_{self._job_counter}"

        self._scheduler.add_job(
            self._run_engagement_job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
        )
        self._log.info("engagement_job_added", job_id=job_id, cron=cron_expr)
        return job_id

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler and begin executing registered jobs."""
        job_count = len(self._scheduler.get_jobs())
        self._log.info("scheduler_starting", jobs=job_count)
        self._scheduler.start()
        self._log.info("scheduler_started")

    def stop(self) -> None:
        """Shut down the scheduler, cancelling all pending jobs."""
        self._log.info("scheduler_stopping")
        self._scheduler.shutdown(wait=False)
        self._log.info("scheduler_stopped")

    # ── Job implementations ──────────────────────────────────────

    async def _run_content_job(self, brief: ContentBrief) -> None:
        """Execute a content generation run."""
        self._log.info("content_job.start", topic=brief.topic)
        try:
            await self._engine.generate_post(brief, publish=True)
            self._log.info("content_job.complete", topic=brief.topic)
        except Exception:
            self._log.exception("content_job.failed", topic=brief.topic)

    async def _run_distribution_job(self) -> None:
        """Check for unshared posts and distribute them."""
        self._log.info("distribution_job.start")
        try:
            pending = await self._engine._db.get_pending_posts()
            if not pending:
                self._log.info("distribution_job.no_pending_posts")
                return

            self._log.info("distribution_job.found_pending", count=len(pending))
            for post in pending:
                if post.wp_post_id is not None:
                    try:
                        await self._engine.distribute_post(post.wp_post_id)
                    except Exception:
                        self._log.exception(
                            "distribution_job.post_failed", wp_post_id=post.wp_post_id
                        )
                else:
                    self._log.warning("distribution_job.no_wp_id", post_id=post.id)

            self._log.info("distribution_job.complete")
        except Exception:
            self._log.exception("distribution_job.failed")

    async def _run_engagement_job(self) -> None:
        """Run the Twitter engagement bot if configured."""
        self._log.info("engagement_job.start")
        try:
            if self._engine._twitter is None:
                self._log.warning("engagement_job.no_twitter_client")
                return

            from astra.twitter.bot import TwitterBot

            bot = TwitterBot(
                twitter=self._engine._twitter,
                llm=self._engine._llm,
                db=self._engine._db,
                config=self._engine._config.twitter_bot,
            )
            stats = await bot.run()
            self._log.info("engagement_job.complete", stats=stats)
        except Exception:
            self._log.exception("engagement_job.failed")
