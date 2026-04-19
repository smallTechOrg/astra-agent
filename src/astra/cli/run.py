"""astra run — start the daemon.

Per spec/product/06-cli.md#daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext


@click.command("run")
@click.pass_obj
def run_cmd(ctx: AstraContext) -> None:
    """Start the Astra daemon."""
    from astra.daemon.daemon import AstraDaemon
    from astra.logging import configure_logging

    log_level = "debug" if ctx.verbosity > 0 else "info"
    configure_logging(json=ctx.json_log, level=log_level)

    daemon = AstraDaemon(ctx.config_dir)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(daemon.start())
