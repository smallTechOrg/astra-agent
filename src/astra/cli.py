from __future__ import annotations

import asyncio
import http.server
import logging
import secrets
import signal
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

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
            getattr(logging, level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _load_config(config_path: str | None) -> AstraConfig:
    """Load configuration from an optional YAML path."""
    path = Path(config_path) if config_path else None
    return AstraConfig.load(config_path=path)


def _handle_cli_error(exc: Exception, command: str, log: structlog.BoundLogger) -> None:
    """Print a human-readable error and exit.  Detects connection errors specially."""
    import httpx

    if isinstance(exc, httpx.ConnectError) or "connection" in str(exc).lower():
        click.echo(
            f"\nConnection failed: {exc}\n\n"
            "Possible causes:\n"
            "  • ASTRA_WORDPRESS__URL is wrong or unreachable\n"
            "  • Credentials are missing — check your .env file\n"
            "  • Network / firewall issue\n\n"
            "Run `astra health` to diagnose each service.",
            err=True,
        )
    else:
        log.error(f"{command}_failed", error=str(exc), exc_info=True)
        click.echo(f"Error: {exc}", err=True)
    sys.exit(1)


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
        _handle_cli_error(exc, "generate", log)


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
        _handle_cli_error(exc, "engage", log)


# ── distribute ────────────────────────────────────────────────────


@main.command()
@click.option("--post-id", required=True, type=int, help="WordPress post ID to distribute.")
@click.option(
    "--linkedin-only", is_flag=True, default=False,
    help="Only distribute to LinkedIn (skip Twitter).",
)
@click.option(
    "--twitter-only", is_flag=True, default=False,
    help="Only distribute to Twitter (skip LinkedIn).",
)
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(exists=False), help=_CONFIG_HELP,
)
@click.pass_context
def distribute(
    ctx: click.Context,
    post_id: int,
    linkedin_only: bool,
    twitter_only: bool,
    config_path: str | None,
) -> None:
    """Distribute an existing WordPress post to social platforms."""
    if linkedin_only and twitter_only:
        click.echo("Cannot use both --linkedin-only and --twitter-only.", err=True)
        sys.exit(1)

    config = _load_config(config_path)
    _configure_logging(
        json_output=ctx.obj.get("json_log", False), level=config.log_level,
    )
    log = structlog.get_logger("astra.cli")

    platforms: set[str] | None = None
    if linkedin_only:
        platforms = {"linkedin"}
    elif twitter_only:
        platforms = {"twitter"}

    async def _run() -> None:
        from astra.core.engine import AstraEngine

        click.echo(f"Fetching WordPress post {post_id}...")
        async with AstraEngine(config) as engine:
            results = await engine.distribute_post(post_id, platforms=platforms)

        click.echo("\nDistribution results:")
        for platform, success in results.items():
            status = "OK" if success else "FAILED"
            click.echo(f"  {platform.capitalize()}: {status}")

        if not results:
            click.echo("  No platforms configured or selected.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("operation_cancelled")
    except Exception as exc:
        _handle_cli_error(exc, "distribute", log)


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
        _handle_cli_error(exc, "health", log)


# ── auth ──────────────────────────────────────────────────────────


@main.group()
def auth() -> None:
    """Authentication helpers for social platforms."""


@auth.command()
@click.option(
    "--client-id", required=True, envvar="LINKEDIN_CLIENT_ID", help="LinkedIn app Client ID.",
)
@click.option(
    "--client-secret", required=True, envvar="LINKEDIN_CLIENT_SECRET",
    help="LinkedIn app Client Secret.",
)
@click.option("--port", default=8989, show_default=True, help="Local callback port.")
@click.option(
    "--scope",
    default="openid profile w_member_social",
    show_default=True,
    help="OAuth scopes.",
)
def linkedin(client_id: str, client_secret: str, port: int, scope: str) -> None:
    """Get a LinkedIn access token via browser OAuth2 flow.

    Opens your browser, asks you to approve access, then prints the
    access token to paste into your .env file.

    Prerequisites (one-time LinkedIn app setup):\n
      1. Create an app at https://www.linkedin.com/developers/apps\n
      2. Add http://localhost:{port}/callback as an Authorized Redirect URL\n
      3. Request the "Share on LinkedIn" product for w_member_social scope
    """
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)

    # Shared container for the callback result
    result: dict[str, str] = {}
    server_ready = threading.Event()
    callback_done = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)
            result["code"] = params.get("code", [""])[0]
            result["state"] = params.get("state", [""])[0]
            result["error"] = params.get("error", [""])[0]

            body = (
                b"<html><body>"
                b"<h2>You can close this tab and return to the terminal.</h2>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            callback_done.set()

        def log_message(self, fmt: str, *args: object) -> None:  # silence request logs
            pass

    server = http.server.HTTPServer(("localhost", port), _Handler)

    def _serve() -> None:
        server_ready.set()
        while not callback_done.is_set():
            server.handle_request()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    server_ready.wait()

    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        })
    )

    click.echo("\nOpening LinkedIn authorization in your browser...")
    click.echo(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    click.echo("Waiting for authorization callback (press Ctrl+C to cancel)...")
    callback_done.wait()

    if result.get("error"):
        click.echo(f"\nAuthorization failed: {result['error']}", err=True)
        sys.exit(1)

    if result.get("state") != state:
        click.echo("\nState mismatch — possible CSRF attack. Aborting.", err=True)
        sys.exit(1)

    code = result.get("code", "")
    if not code:
        click.echo("\nNo authorization code received.", err=True)
        sys.exit(1)

    click.echo("\nExchanging authorization code for access token...")

    import httpx

    try:
        resp = httpx.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except httpx.HTTPError as exc:
        click.echo(f"\nToken exchange failed: {exc}", err=True)
        sys.exit(1)

    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", "unknown")

    click.echo("\n" + "=" * 60)
    click.echo("LinkedIn access token obtained successfully!")
    if str(expires_in).isdigit():
        days = int(expires_in) // 86400
        click.echo(f"Expires in: {expires_in} seconds (~{days} days)")
    else:
        click.echo(f"Expires in: {expires_in}")
    click.echo("=" * 60)
    click.echo("\nAdd this to your .env file:\n")
    click.echo(f"  ASTRA_LINKEDIN__ACCESS_TOKEN={access_token}")
    click.echo("\nTo post as a company page, also add:")
    click.echo("  ASTRA_LINKEDIN__ORGANIZATION_ID=<your_org_id>\n")
    click.echo("(Find your org ID in the LinkedIn company admin panel —")
    click.echo(" search the page source for 'organizationUrn')\n")


# ── version ──────────────────────────────────────────────────────


@main.command()
def version() -> None:
    """Print the Astra Agent version."""
    click.echo(f"astra-agent {__version__}")
