"""astra distribute / astra cadence run — manual triggers.

Per spec/product/06-cli.md#manual-distribution.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext


@click.command("distribute")
@click.option("--tenant", "tenant_id", required=True, metavar="ID")
@click.option("--wp-post-id", required=True, metavar="POST_ID")
@click.option(
    "--platform",
    type=click.Choice(["linkedin", "twitter"]),
    default=None,
    help="Distribute to only this platform. Default: all enabled.",
)
@click.option("--force", is_flag=True, help="Re-distribute even if already sent.")
@click.pass_obj
def distribute_cmd(
    ctx: AstraContext,
    tenant_id: str,
    wp_post_id: str,
    platform: str | None,
    force: bool,
) -> None:
    """Fetch a WordPress post and distribute it manually."""
    exit_code = asyncio.run(_run_distribute(ctx, tenant_id, wp_post_id, platform, force))
    sys.exit(exit_code)


async def _run_distribute(
    ctx: AstraContext,
    tenant_id: str,
    wp_post_id: str,
    platform: str | None,
    force: bool,
) -> int:
    cfg = ctx.load_config()

    if tenant_id not in cfg.tenants:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

    loaded = cfg.tenants[tenant_id]
    if loaded.degraded:
        click.echo(f"Error: tenant {tenant_id!r} is degraded: {loaded.degraded_reason}", err=True)
        return 2

    db_path = ctx.config_dir.parent / cfg.operator.database_path
    from astra.db import Database, migrate
    db = Database(db_path)
    await db.connect()
    await migrate(db)

    try:
        from astra.db.repos import DistributionRecordsRepo, PublishEventsRepo, TenantsRepo
        await TenantsRepo(db).upsert(tenant_id, loaded.config.name, loaded.config.enabled)

        # Check if event already exists.
        events_repo = PublishEventsRepo(db)
        existing = await events_repo.get_by_source_id(tenant_id, "wordpress", wp_post_id)

        if existing is None:
            # Fetch from WordPress.
            source_secret = loaded.secrets.get(loaded.config.source.app_password_env)
            app_password = source_secret.get_secret_value() if source_secret else ""
            from astra.sources import get_source
            source = get_source("wordpress")()
            await source.poll(loaded.config, db, app_password=app_password)
            # Find the specific post.
            event_rec = await events_repo.get_by_source_id(tenant_id, "wordpress", wp_post_id)
            if event_rec is None:
                click.echo(f"Error: WordPress post {wp_post_id!r} not found.", err=True)
                return 1
        else:
            event_rec = existing

        # Check if already sent (and --force not set).
        if not force:
            platforms = [platform] if platform else ["linkedin", "twitter"]
            for p in platforms:
                dist = await DistributionRecordsRepo(db).get(
                    tenant_id=tenant_id,
                    publish_event_id=event_rec.id,
                    platform=p,
                )
                if dist and dist.status == "sent":
                    click.echo(
                        f"Error: event {event_rec.id} already sent to {p}. Use --force to re-distribute.",
                        err=True,
                    )
                    return 1

        api_key_env = cfg.operator.llm.api_key_env
        api_key_secret = loaded.secrets.get(api_key_env)
        import os
        api_key = (
            api_key_secret.get_secret_value()
            if api_key_secret
            else os.environ.get(api_key_env, "")
        )
        from astra.llm.factory import build_llm_client
        from astra.prompts.resolver import PromptResolver
        llm = build_llm_client(cfg.operator.llm, api_key=api_key)
        operator_prompts = ctx.config_dir.parent / "prompts"
        tenant_prompts = ctx.config_dir / "tenants" / tenant_id / "prompts"
        prompts = PromptResolver(
            operator_prompts_dir=operator_prompts,
            tenant_prompts_dir=tenant_prompts if tenant_prompts.exists() else None,
        )

        from astra.daemon.distributor import _distribute_to
        from astra.domain import PublishEvent

        event = PublishEvent(
            tenant_id=event_rec.tenant_id,
            source_name=event_rec.source_name,
            source_post_id=event_rec.source_post_id,
            title=event_rec.title,
            url=event_rec.url,
            excerpt=event_rec.excerpt,
            published_at=event_rec.published_at,
            db_id=event_rec.id,
        )

        platforms_to_run = [platform] if platform else []
        if not platforms_to_run:
            if loaded.config.destinations.linkedin.enabled:
                platforms_to_run.append("linkedin")
            if loaded.config.destinations.twitter.enabled:
                platforms_to_run.append("twitter")

        for p in platforms_to_run:
            await _distribute_to(loaded.config, event, db, llm, prompts, loaded.secrets, p)
            click.echo(f"Distributed to {p}.")

        return 0
    finally:
        await db.close()


# ── cadence sub-group ─────────────────────────────────────────────

@click.group("cadence")
def cadence_group() -> None:
    """Manage cadences."""


@cadence_group.command("run")
@click.option("--tenant", "tenant_id", required=True, metavar="ID")
@click.option("--name", "cadence_name", required=True, metavar="NAME")
@click.option("--force", is_flag=True, help="Run even if cadence is disabled.")
@click.pass_obj
def cadence_run(ctx: AstraContext, tenant_id: str, cadence_name: str, force: bool) -> None:
    """Trigger one tick of a named cadence immediately."""
    exit_code = asyncio.run(_run_cadence(ctx, tenant_id, cadence_name, force))
    sys.exit(exit_code)


async def _run_cadence(
    ctx: AstraContext, tenant_id: str, cadence_name: str, force: bool
) -> int:
    cfg = ctx.load_config()

    if tenant_id not in cfg.tenants:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

    loaded = cfg.tenants[tenant_id]
    cadence_cfgs = [c for c in loaded.config.cadences if c.name == cadence_name]
    if not cadence_cfgs:
        click.echo(f"Error: cadence {cadence_name!r} not found for tenant {tenant_id!r}.", err=True)
        return 1

    cadence_cfg = cadence_cfgs[0]
    if not cadence_cfg.enabled and not force:
        click.echo(f"Error: cadence {cadence_name!r} is disabled. Use --force to run anyway.", err=True)
        return 1

    db_path = ctx.config_dir.parent / cfg.operator.database_path
    from astra.db import Database, migrate
    db = Database(db_path)
    await db.connect()
    await migrate(db)

    try:
        api_key_env = cfg.operator.llm.api_key_env
        api_key_secret = loaded.secrets.get(api_key_env)
        import os
        api_key = (
            api_key_secret.get_secret_value()
            if api_key_secret
            else os.environ.get(api_key_env, "")
        )
        from astra.llm.factory import build_llm_client
        from astra.prompts.resolver import PromptResolver
        llm = build_llm_client(cfg.operator.llm, api_key=api_key)
        operator_prompts = ctx.config_dir.parent / "prompts"
        tenant_prompts = ctx.config_dir / "tenants" / tenant_id / "prompts"
        prompts = PromptResolver(
            operator_prompts_dir=operator_prompts,
            tenant_prompts_dir=tenant_prompts if tenant_prompts.exists() else None,
        )
        from astra.daemon.runner import TenantRunner
        from astra.db.repos import TenantsRepo
        await TenantsRepo(db).upsert(tenant_id, loaded.config.name, loaded.config.enabled)
        runner = TenantRunner(
            tenant=loaded.config,
            db=db,
            llm=llm,
            prompts=prompts,
            secrets=loaded.secrets,
        )
        await runner.cadence_tick(cadence_cfg)
        click.echo(f"Cadence {cadence_name!r} tick completed.")
        return 0
    finally:
        await db.close()
