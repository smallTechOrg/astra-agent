from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import click
import structlog

from astra import __version__
from astra.config import AstraConfig
from astra.wordpress.models import ContentBrief

_CONFIG_HELP = "Path to config YAML."


def _configure_logging(*, json_output: bool = False, level: str = "INFO") -> None:
    """Set up structlog with a console or JSON renderer."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, level.upper(), structlog.INFO),  # type: ignore[attr-defined]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _load_config(config_path: str | None) -> AstraConfig:
    """Load configuration from an optional YAML path."""
    path = Path(config_path) if config_path else None
    return AstraConfig.load(config_path=path)


# ── CLI group ────────────────────────────────────────────────────


@click.group()
@click.option(
    "--json-log",
    is_flag=True,
    default=False,
    help="Emit logs as JSON instead of coloured console output.",
)
@click.pass_context
def main(ctx: click.Context, json_log: bool) -> None:
    """Astra Agent -- AI content engine for WordPress."""
    ctx.ensure_object(dict)
    ctx.obj["json_log"] = json_log


# ── generate ─────────────────────────────────────────────────────


@main.command()
@click.option("--topic", required=True, help="Blog post topic.")
@click.option(
    "--tone", default="professional", show_default=True, help="Writing tone.",
)
@click.option(
    "--word-count", default=1500, show_default=True, type=int,
    help="Target word count.",
)
@click.option("--keywords", default="", help="Comma-separated keywords.")
@click.option(
    "--publish", is_flag=True, default=False, help="Publish immediately.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Print generated content without publishing.",
)
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(exists=False), help=_CONFIG_HELP,
)
@click.pass_context
def generate(
    ctx: click.Context,
    topic: str,
    tone: str,
    word_count: int,
    keywords: str,
    publish: bool,
    dry_run: bool,
    config_path: str | None,
) -> None:
    """Generate a blog post from a topic brief."""
    config = _load_config(config_path)
    _configure_logging(
        json_output=ctx.obj.get("json_log", False), level=config.log_level,
    )
    log = structlog.get_logger("astra.cli")

    keyword_list = (
        [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
    )

    brief = ContentBrief(
        topic=topic,
        tone=tone,
        target_word_count=word_count,
        keywords=keyword_list,
    )

    async def _run() -> None:
        from astra.core.engine import AstraEngine

        async with AstraEngine(config) as engine:
            result = await engine.generate_post(
                brief, publish=publish, dry_run=dry_run,
            )

        if dry_run:
            click.echo("\n--- Generated Post (dry run) ---\n")
            assert isinstance(result, dict)
            click.echo(f"Title:   {result['title']}")
            click.echo(f"Status:  {result['status']}")
            click.echo(f"Tags:    {', '.join(result['tags'])}")
            click.echo(f"Excerpt: {result['excerpt']}\n")
            click.echo(result["content"])
        else:
            from astra.wordpress.models import WordPressPostResponse

            assert isinstance(result, WordPressPostResponse)
            click.echo("\nPost created successfully!")
            click.echo(f"  ID:     {result.id}")
            click.echo(f"  Status: {result.status}")
            click.echo(f"  Link:   {result.link}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("operation_cancelled")
    except Exception as exc:
        log.error("generate_failed", error=str(exc), exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ── run (daemon mode) ────────────────────────────────────────────


@main.command()
@click.option(
    "--topic", default="technology trends", show_default=True,
    help="Default topic for scheduled posts.",
)
@click.option(
    "--tone", default="professional", show_default=True,
    help="Writing tone for scheduled posts.",
)
@click.option(
    "--word-count", default=1500, show_default=True, type=int,
    help="Target word count.",
)
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(exists=False), help=_CONFIG_HELP,
)
@click.pass_context
def run(
    ctx: click.Context,
    topic: str,
    tone: str,
    word_count: int,
    config_path: str | None,
) -> None:
    """Start Astra in daemon mode with scheduled jobs."""
    config = _load_config(config_path)
    _configure_logging(
        json_output=ctx.obj.get("json_log", False), level=config.log_level,
    )
    log = structlog.get_logger("astra.cli")

    if not config.scheduler.enabled:
        click.echo(
            "Scheduler is disabled in config. "
            "Set scheduler.enabled = true to use daemon mode.",
        )
        sys.exit(1)

    brief = ContentBrief(
        topic=topic, tone=tone, target_word_count=word_count,
    )

    async def _run() -> None:
        from astra.core.engine import AstraEngine
        from astra.core.scheduler import AstraScheduler

        shutdown_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_event.set)

        async with AstraEngine(config) as engine:
            scheduler = AstraScheduler(engine)
            scheduler.add_content_job(config.scheduler.post_cron, brief)
            scheduler.add_distribution_job(config.scheduler.share_cron)

            if (
                config.twitter_bot.enabled
                and engine._twitter is not None
            ):
                scheduler.add_engagement_job(config.scheduler.engage_cron)

            scheduler.start()
            click.echo("Astra daemon started. Press Ctrl+C to stop.")
            log.info("daemon_running")

            await shutdown_event.wait()

            scheduler.stop()
            log.info("daemon_stopped")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.error("daemon_failed", error=str(exc), exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ── engage (one-shot bot run) ────────────────────────────────────


@main.command()
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(exists=False), help=_CONFIG_HELP,
)
@click.pass_context
def engage(ctx: click.Context, config_path: str | None) -> None:
    """Run the Twitter engagement bot once."""
    config = _load_config(config_path)
    _configure_logging(
        json_output=ctx.obj.get("json_log", False), level=config.log_level,
    )
    log = structlog.get_logger("astra.cli")

    if not config.twitter.bearer_token:
        click.echo("Twitter credentials not configured.", err=True)
        sys.exit(1)

    async def _run() -> None:
        from astra.core.engine import AstraEngine
        from astra.twitter.bot import TwitterBot

        async with AstraEngine(config) as engine:
            if engine._twitter is None:
                click.echo("Twitter client not initialized.", err=True)
                return

            bot = TwitterBot(
                twitter=engine._twitter,
                llm=engine._llm,
                db=engine._db,
                config=config.twitter_bot,
            )
            stats = await bot.run()
            click.echo("\nEngagement run complete:")
            click.echo(f"  Likes:   {stats['likes']}")
            click.echo(f"  Replies: {stats['replies']}")
            click.echo(f"  Follows: {stats['follows']}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("operation_cancelled")
    except Exception as exc:
        log.error("engage_failed", error=str(exc), exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ── health ───────────────────────────────────────────────────────


@main.command()
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(exists=False), help=_CONFIG_HELP,
)
@click.pass_context
def health(ctx: click.Context, config_path: str | None) -> None:
    """Check that all API connections are healthy."""
    config = _load_config(config_path)
    _configure_logging(
        json_output=ctx.obj.get("json_log", False), level=config.log_level,
    )
    log = structlog.get_logger("astra.cli")

    async def _run() -> None:
        from astra.storage.database import Database
        from astra.wordpress.client import WordPressClient

        # WordPress
        wp = WordPressClient(
            base_url=config.wordpress.url,
            username=config.wordpress.username,
            app_password=config.wordpress.app_password,
        )
        try:
            await wp.health_check()
            click.echo("WordPress API:  OK")
        except Exception as exc:
            click.echo(f"WordPress API:  FAILED ({exc})", err=True)
        finally:
            await wp.close()

        # LLM
        from astra.llm.factory import create_llm_client

        try:
            llm = create_llm_client(
                provider=config.llm.provider,
                api_key=config.llm.api_key,
                model=config.llm.model,
            )
            await llm.generate_content("Say OK.", max_tokens=5)
            click.echo(f"LLM ({config.llm.provider}): OK")
        except Exception as exc:
            click.echo(
                f"LLM ({config.llm.provider}): FAILED ({exc})", err=True,
            )

        # Database
        try:
            async with Database(config.database_path):
                pass
            click.echo("Database:       OK")
        except Exception as exc:
            click.echo(f"Database:       FAILED ({exc})", err=True)

        # Twitter (optional)
        if config.twitter.bearer_token:
            from astra.twitter.client import TwitterClient

            tw = TwitterClient(
                api_key=config.twitter.api_key,
                api_secret=config.twitter.api_secret,
                access_token=config.twitter.access_token,
                access_secret=config.twitter.access_secret,
                bearer_token=config.twitter.bearer_token,
            )
            try:
                async with tw:
                    await tw.health_check()
                click.echo("Twitter API:    OK")
            except Exception as exc:
                click.echo(
                    f"Twitter API:    FAILED ({exc})", err=True,
                )

        # LinkedIn (optional)
        if config.linkedin.access_token:
            from astra.linkedin.client import LinkedInClient

            li = LinkedInClient(
                access_token=config.linkedin.access_token,
                organization_id=config.linkedin.organization_id or None,
            )
            try:
                async with li:
                    await li.health_check()
                click.echo("LinkedIn API:   OK")
            except Exception as exc:
                click.echo(
                    f"LinkedIn API:   FAILED ({exc})", err=True,
                )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("operation_cancelled")
    except Exception as exc:
        log.error("health_check_failed", error=str(exc), exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ── version ──────────────────────────────────────────────────────


@main.command()
def version() -> None:
    """Print the Astra Agent version."""
    click.echo(f"astra-agent {__version__}")
