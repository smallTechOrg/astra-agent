"""Tenant management commands: add, list, enable, disable, remove.

Per spec/product/06-cli.md#tenant-management.
All state is stored in PostgreSQL (spec/product/05-config.md#db-first).
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


@click.group("tenant")
def tenant_group() -> None:
    """Manage tenants."""


@tenant_group.command("add")
@click.argument("tenant_id")
@click.option("--name", default=None, help="Display name for the tenant.")
@click.pass_obj
def tenant_add(ctx: AstraContext, tenant_id: str, name: str | None) -> None:
    """Create a new tenant row in the database (enabled=false by default)."""
    if not _SLUG_RE.match(tenant_id) or len(tenant_id) < 2 or len(tenant_id) > 40:
        click.echo(
            f"Error: tenant ID {tenant_id!r} is invalid. "
            "Must match [a-z0-9][a-z0-9-]*[a-z0-9], 2-40 chars.",
            err=True,
        )
        sys.exit(3)

    display_name = name or tenant_id
    asyncio.run(_create_tenant(ctx.database_url, tenant_id, display_name))
    click.echo(f"Created tenant {tenant_id!r} (enabled=false).")
    click.echo("Configure source/destinations via `astra ui`, then enable with:")
    click.echo(f"  astra tenant enable {tenant_id}")


async def _create_tenant(database_url: str, tenant_id: str, name: str) -> None:
    from astra.db import Database, migrate
    from astra.db.repos import TenantConfigRepo, TenantsRepo

    async with Database(database_url) as db:
        await migrate(db)
        async with db.pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM tenants WHERE id = $1", tenant_id
            )
            if existing:
                click.echo(
                    f"Error: tenant {tenant_id!r} already exists.", err=True
                )
                sys.exit(1)
            from datetime import UTC, datetime
            now = datetime.now(UTC)
            await conn.execute(
                "INSERT INTO tenants (id, name, enabled, created_at, updated_at) "
                "VALUES ($1, $2, false, $3, $3)",
                tenant_id, name, now,
            )
            await conn.execute(
                "INSERT INTO tenant_config (tenant_id, updated_at) VALUES ($1, $2)",
                tenant_id, now,
            )
        _ = TenantConfigRepo(db)  # ensure import used; actual insert done via raw conn above
        _ = TenantsRepo(db)


@tenant_group.command("list")
@click.pass_obj
def tenant_list(ctx: AstraContext) -> None:
    """List all tenants with status."""
    asyncio.run(_list_tenants(ctx.database_url))


async def _list_tenants(database_url: str) -> None:
    from astra.db import Database, migrate
    from astra.db.repos import DistributionRecordsRepo, TenantsRepo

    async with Database(database_url) as db:
        await migrate(db)
        rows = await TenantsRepo(db).list_all()

        if not rows:
            click.echo("No tenants configured.")
            return

        header = f"{'ID':<20} {'NAME':<25} {'ENABLED':<8} PENDING"
        click.echo(header)
        click.echo("-" * len(header))

        dist_repo = DistributionRecordsRepo(db)
        for row in rows:
            tenant_id: str = row["id"]
            enabled_str = "yes" if row["enabled"] else "no"
            pending = await dist_repo.count_pending(tenant_id)
            click.echo(
                f"{tenant_id:<20} {str(row['name']):<25} {enabled_str:<8} {pending}"
            )


@tenant_group.command("enable")
@click.argument("tenant_id")
@click.pass_obj
def tenant_enable(ctx: AstraContext, tenant_id: str) -> None:
    """Enable a tenant (requires daemon restart)."""
    asyncio.run(_set_enabled(ctx.database_url, tenant_id, enabled=True))
    click.echo(f"Tenant {tenant_id!r} enabled. Restart the daemon to take effect.")


@tenant_group.command("disable")
@click.argument("tenant_id")
@click.pass_obj
def tenant_disable(ctx: AstraContext, tenant_id: str) -> None:
    """Disable a tenant (requires daemon restart)."""
    asyncio.run(_set_enabled(ctx.database_url, tenant_id, enabled=False))
    click.echo(f"Tenant {tenant_id!r} disabled. Restart the daemon to take effect.")


async def _set_enabled(database_url: str, tenant_id: str, *, enabled: bool) -> None:
    from datetime import UTC, datetime

    from astra.db import Database, migrate

    async with Database(database_url) as db:
        await migrate(db)
        result = await db.fetch_one(
            "SELECT id FROM tenants WHERE id = $1", tenant_id
        )
        if result is None:
            click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
            sys.exit(1)
        await db.execute(
            "UPDATE tenants SET enabled = $1, updated_at = $2 WHERE id = $3",
            enabled, datetime.now(UTC), tenant_id,
        )


@tenant_group.command("remove")
@click.argument("tenant_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
def tenant_remove(ctx: AstraContext, tenant_id: str, force: bool) -> None:
    """Remove a tenant and all its database rows (CASCADE)."""
    if not force:
        click.confirm(
            f"This will delete all DB rows for tenant {tenant_id!r}. Continue?",
            abort=True,
        )
    asyncio.run(_remove_tenant(ctx.database_url, tenant_id))
    click.echo(f"Tenant {tenant_id!r} removed.")


async def _remove_tenant(database_url: str, tenant_id: str) -> None:
    from astra.db import Database, migrate
    from astra.db.repos import TenantsRepo

    async with Database(database_url) as db:
        await migrate(db)
        result = await db.fetch_one(
            "SELECT id FROM tenants WHERE id = $1", tenant_id
        )
        if result is None:
            click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
            sys.exit(1)
        await TenantsRepo(db).delete(tenant_id)
