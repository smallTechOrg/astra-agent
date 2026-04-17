"""astra run — start the daemon.

Per spec/product/06-cli.md#daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext


@click.command("run")
@click.option(
    "--tenant",
    "tenants",
    multiple=True,
    metavar="ID",
    help="Run only the specified tenant(s). May be repeated.",
)
@click.pass_obj
def run_cmd(ctx: AstraContext, tenants: tuple[str, ...]) -> None:
    """Start the Astra daemon."""
    from astra.daemon.daemon import AstraDaemon
    from astra.logging import configure_logging

    cfg = ctx.load_config()
    log_level = "debug" if ctx.verbosity > 0 else cfg.operator.log_level
    configure_logging(json=ctx.json_log, level=log_level)

    db_path = ctx.config_dir.parent / cfg.operator.database_path

    if tenants:
        # Restrict to requested tenant IDs.
        unknown = set(tenants) - set(cfg.tenants)
        if unknown:
            click.echo(f"Error: unknown tenant(s): {', '.join(sorted(unknown))}", err=True)
            sys.exit(1)
        # Temporarily disable tenants not in the filter.
        for tid, loaded in cfg.tenants.items():
            if tid not in tenants:
                loaded.config = loaded.config.model_copy(update={"enabled": False})

    daemon = AstraDaemon(ctx.config_dir, db_path=db_path)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(daemon.start())
