"""astra events / astra tweets — introspection commands.

Per spec/product/06-cli.md#introspection.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext


@click.command("events")
@click.option("--tenant", "tenant_id", required=True, metavar="ID")
@click.option("--limit", default=20, show_default=True)
@click.pass_obj
def events_cmd(ctx: AstraContext, tenant_id: str, limit: int) -> None:
    """List recent publish events with distribution status."""
    exit_code = asyncio.run(_run_events(ctx, tenant_id, limit))
    sys.exit(exit_code)


async def _run_events(ctx: AstraContext, tenant_id: str, limit: int) -> int:
    cfg = ctx.load_config()
    if tenant_id not in cfg.tenants:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

    db_path = ctx.config_dir.parent / cfg.operator.database_path
    if not db_path.exists():
        click.echo("No database found. Has the daemon run yet?")
        return 0

    from astra.db import Database
    db = Database(db_path)
    await db.connect()
    try:
        from astra.db.repos import DistributionRecordsRepo, PublishEventsRepo
        events = await PublishEventsRepo(db).list_recent(tenant_id, limit=limit)
        if not events:
            click.echo("No publish events found.")
            return 0

        click.echo(f"{'ID':<5} {'DETECTED':<15} {'TITLE':<40} {'LINKEDIN':<15} TWITTER")
        click.echo("-" * 100)

        dist_repo = DistributionRecordsRepo(db)
        for ev in events:
            li_recs = await dist_repo.list_for_event(tenant_id, ev.id)
            li_status = next((r.status + (f" ({r.error})" if r.error else "") for r in li_recs if r.platform == "linkedin"), "-")
            tw_status = next((r.status + (f" ({r.error})" if r.error else "") for r in li_recs if r.platform == "twitter"), "-")
            title = ev.title[:38] + "…" if len(ev.title) > 39 else ev.title
            detected = ev.detected_at[:16]
            click.echo(f"{ev.id:<5} {detected:<15} {title:<40} {li_status:<15} {tw_status}")
    finally:
        await db.close()

    return 0


@click.command("tweets")
@click.option("--tenant", "tenant_id", required=True, metavar="ID")
@click.option("--cadence", "cadence_name", default=None, metavar="NAME")
@click.option("--limit", default=20, show_default=True)
@click.pass_obj
def tweets_cmd(ctx: AstraContext, tenant_id: str, cadence_name: str | None, limit: int) -> None:
    """List recent cadence tweets with status."""
    exit_code = asyncio.run(_run_tweets(ctx, tenant_id, cadence_name, limit))
    sys.exit(exit_code)


async def _run_tweets(ctx: AstraContext, tenant_id: str, cadence_name: str | None, limit: int) -> int:
    cfg = ctx.load_config()
    if tenant_id not in cfg.tenants:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

    db_path = ctx.config_dir.parent / cfg.operator.database_path
    if not db_path.exists():
        click.echo("No database found. Has the daemon run yet?")
        return 0

    from astra.db import Database
    db = Database(db_path)
    await db.connect()
    try:
        from astra.db.repos import ScheduledTweetsRepo
        tweets = await ScheduledTweetsRepo(db).list_recent(tenant_id, cadence_name=cadence_name, limit=limit)
        if not tweets:
            click.echo("No tweets found.")
            return 0

        click.echo(f"{'CADENCE':<20} {'POSTED':<16} {'STATUS':<10} {'ID':<20} TEXT")
        click.echo("-" * 100)
        for t in tweets:
            text_preview = (t.text or "")[:40]
            pid = t.platform_post_id or "-"
            click.echo(f"{t.cadence_name:<20} {t.posted_at[:16]:<16} {t.status:<10} {pid:<20} {text_preview}")
    finally:
        await db.close()

    return 0
