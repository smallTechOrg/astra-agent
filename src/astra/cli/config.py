"""CLI commands for operator config.

Per spec/product/06-cli.md:
- ``astra config show`` — prints current operator_config from DB.
- ``astra config set <key> <value>`` — updates a single column.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext

if __name__ == "__main__":  # pragma: no cover – never executed
    pass


@click.group("config")
def config_group() -> None:
    """View / update operator-level configuration."""


@config_group.command("show")
@click.pass_obj
def config_show(ctx: AstraContext) -> None:
    """Print operator_config from the database."""
    from astra.config.loader import ConfigLoader
    from astra.db import Database, migrate
    from astra.db.repos import OperatorConfigRepo

    async def _run() -> None:
        loader = ConfigLoader(ctx.config_dir)
        db_url = loader.load_bootstrap()
        db = Database(db_url)
        await db.connect()
        try:
            await migrate(db)
            record = await OperatorConfigRepo(db).get()
            if record is None:
                click.echo("operator_config row missing — run migrations first.", err=True)
                raise SystemExit(1)
            click.echo(f"llm_provider          = {record.llm_provider}")
            click.echo(f"llm_model             = {record.llm_model}")
            click.echo(f"llm_temperature       = {record.llm_temperature}")
            click.echo(f"llm_max_tokens        = {record.llm_max_tokens}")
            click.echo(f"log_level             = {record.log_level}")
            click.echo(f"share_sweep_cron      = {record.share_sweep_cron}")
            click.echo(f"startup_grace_seconds = {record.startup_grace_seconds}")
            click.echo(f"updated_at            = {record.updated_at.isoformat()}")
        finally:
            await db.close()

    asyncio.run(_run())


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_obj
def config_set(ctx: AstraContext, key: str, value: str) -> None:
    """Set an operator_config column: ``astra config set <key> <value>``."""
    from astra.config.loader import ConfigLoader
    from astra.db import Database, migrate
    from astra.db.repos import OperatorConfigRepo

    allowed = {
        "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
        "log_level", "share_sweep_cron", "startup_grace_seconds",
    }
    if key not in allowed:
        click.echo(f"Unknown key '{key}'. Allowed: {', '.join(sorted(allowed))}", err=True)
        raise SystemExit(3)

    # Coerce numeric types.
    coerced: object = value
    if key == "llm_temperature":
        try:
            coerced = float(value)
        except ValueError:
            click.echo(f"llm_temperature must be a number, got: {value}", err=True)
            raise SystemExit(3)  # noqa: B904
    elif key in ("llm_max_tokens", "startup_grace_seconds"):
        try:
            coerced = int(value)
        except ValueError:
            click.echo(f"{key} must be an integer, got: {value}", err=True)
            raise SystemExit(3)  # noqa: B904

    async def _run() -> None:
        loader = ConfigLoader(ctx.config_dir)
        db_url = loader.load_bootstrap()
        db = Database(db_url)
        await db.connect()
        try:
            await migrate(db)
            await OperatorConfigRepo(db).update(**{key: coerced})
            click.echo(f"{key} = {coerced}")
        finally:
            await db.close()

    asyncio.run(_run())
