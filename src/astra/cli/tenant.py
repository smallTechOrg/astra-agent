"""Tenant management commands: add, list, enable, disable, remove.

Per spec/product/06-cli.md#tenant-management.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click
import yaml

if TYPE_CHECKING:
    from pathlib import Path

    from astra.cli.context import AstraContext

_SLUG_RE = r"^[a-z0-9][a-z0-9-]*[a-z0-9]$"

_TENANT_TEMPLATE = """\
# Tenant configuration for {id}
# See spec/product/05-config.md for all options.

id: {id}
name: "{name}"
enabled: false

source:
  type: wordpress
  url: "https://your-wordpress-site.com"
  username: "admin"
  app_password_env: "WP_APP_PASSWORD"
  poll_cron: "*/5 * * * *"

destinations:
  linkedin:
    enabled: false
    organization_id: ""
    access_token_env: "LINKEDIN_ACCESS_TOKEN"

  twitter:
    enabled: false
    api_key_env: "TWITTER_API_KEY"
    api_secret_env: "TWITTER_API_SECRET"
    access_token_env: "TWITTER_ACCESS_TOKEN"
    access_secret_env: "TWITTER_ACCESS_SECRET"

cadences: []
"""


@click.group("tenant")
def tenant_group() -> None:
    """Manage tenants."""


@tenant_group.command("add")
@click.argument("tenant_id")
@click.option("--name", default=None, help="Display name for the tenant.")
@click.pass_obj
def tenant_add(ctx: AstraContext, tenant_id: str, name: str | None) -> None:
    """Create a new tenant configuration directory."""
    import re

    if not re.match(_SLUG_RE, tenant_id) or len(tenant_id) < 2 or len(tenant_id) > 40:
        click.echo(f"Error: tenant ID {tenant_id!r} is invalid. Must match [a-z0-9][a-z0-9-]*[a-z0-9], 2-40 chars.", err=True)
        sys.exit(3)

    tenant_dir = ctx.config_dir / "tenants" / tenant_id
    if tenant_dir.exists():
        click.echo(f"Error: tenant {tenant_id!r} already exists at {tenant_dir}.", err=True)
        sys.exit(1)

    tenant_dir.mkdir(parents=True)
    display_name = name or tenant_id
    (tenant_dir / "tenant.yaml").write_text(_TENANT_TEMPLATE.format(id=tenant_id, name=display_name))
    (tenant_dir / ".env").write_text("# Per-tenant secrets — gitignored\n")

    click.echo(f"Created tenant {tenant_id!r} at {tenant_dir}")
    click.echo("  Edit tenant.yaml and .env, then run: astra tenant enable " + tenant_id)


@tenant_group.command("list")
@click.pass_obj
def tenant_list(ctx: AstraContext) -> None:
    """List all tenants with status."""
    import asyncio

    cfg = ctx.load_config()

    if not cfg.tenants and not cfg.load_errors:
        click.echo("No tenants configured.")
        return

    # Print failed-to-load tenants first.
    for tid, err in cfg.load_errors.items():
        click.echo(f"{tid:<20} (load error: {err})")

    if not cfg.tenants:
        return

    db_path = ctx.config_dir.parent / cfg.operator.database_path

    async def _get_pending(tenant_id: str) -> int:
        if not db_path.exists():
            return 0
        from astra.db import Database
        from astra.db.repos import DistributionRecordsRepo
        db = Database(db_path)
        await db.connect()
        try:
            return await DistributionRecordsRepo(db).count_pending(tenant_id)
        finally:
            await db.close()

    header = f"{'ID':<20} {'NAME':<25} {'ENABLED':<8} {'STATUS':<12} PENDING"
    click.echo(header)
    click.echo("-" * len(header))

    for tenant_id, loaded in sorted(cfg.tenants.items()):
        enabled_str = "yes" if loaded.config.enabled else "no"
        if not loaded.config.enabled:
            status = "-"
        elif loaded.degraded:
            status = "degraded"
        else:
            status = "ok"
        pending = asyncio.run(_get_pending(tenant_id))
        click.echo(
            f"{tenant_id:<20} {loaded.config.name:<25} {enabled_str:<8} {status:<12} {pending}"
        )


@tenant_group.command("enable")
@click.argument("tenant_id")
@click.pass_obj
def tenant_enable(ctx: AstraContext, tenant_id: str) -> None:
    """Enable a tenant (requires daemon restart)."""
    _set_enabled(ctx.config_dir, tenant_id, enabled=True)
    click.echo(f"Tenant {tenant_id!r} enabled. Restart the daemon to take effect.")


@tenant_group.command("disable")
@click.argument("tenant_id")
@click.pass_obj
def tenant_disable(ctx: AstraContext, tenant_id: str) -> None:
    """Disable a tenant (requires daemon restart)."""
    _set_enabled(ctx.config_dir, tenant_id, enabled=False)
    click.echo(f"Tenant {tenant_id!r} disabled. Restart the daemon to take effect.")


@tenant_group.command("remove")
@click.argument("tenant_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def tenant_remove(ctx: AstraContext, tenant_id: str, force: bool) -> None:
    """Remove a tenant and all its DB rows."""
    import asyncio
    import shutil

    tenant_dir = ctx.config_dir / "tenants" / tenant_id
    if not tenant_dir.exists():
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        sys.exit(1)

    if not force:
        click.confirm(
            f"This will delete all config and DB rows for tenant {tenant_id!r}. Continue?",
            abort=True,
        )

    cfg = ctx.load_config()
    db_path = ctx.config_dir.parent / cfg.operator.database_path
    if db_path.exists():
        async def _delete_db_rows() -> None:
            from astra.db import Database
            from astra.db.repos import TenantsRepo
            db = Database(db_path)
            await db.connect()
            try:
                await TenantsRepo(db).delete(tenant_id)
            finally:
                await db.close()

        asyncio.run(_delete_db_rows())

    shutil.rmtree(tenant_dir)
    click.echo(f"Tenant {tenant_id!r} removed.")


def _set_enabled(config_dir: Path, tenant_id: str, *, enabled: bool) -> None:
    yaml_path = config_dir / "tenants" / tenant_id / "tenant.yaml"
    if not yaml_path.exists():
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        sys.exit(1)

    raw: dict[str, object] = yaml.safe_load(yaml_path.read_text()) or {}
    raw["enabled"] = enabled
    yaml_path.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
