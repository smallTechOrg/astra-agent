"""CLI entry point for Astra.

Per spec/product/06-cli.md — `astra` command tree.
Exit codes: 0 success, 1 operator error, 2 runtime error, 3 validation error.
"""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli.auth import auth_group
from astra.cli.context import AstraContext
from astra.cli.distribute import cadence_group, distribute_cmd
from astra.cli.health import health_cmd
from astra.cli.introspect import events_cmd, tweets_cmd
from astra.cli.run import run_cmd
from astra.cli.tenant import tenant_group


@click.group()
@click.option("--json-log", is_flag=True, help="Emit JSON logs.")
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default=Path("config"),
    show_default=True,
    help="Config root directory.",
)
@click.option("-v", "verbosity", count=True, help="Increase verbosity (-v = info, -vv = debug).")
@click.version_option(package_name="astra-agent", prog_name="astra")
@click.pass_context
def main(
    click_ctx: click.Context,
    json_log: bool,
    config_dir: Path,
    verbosity: int,
) -> None:
    """Astra — multi-tenant content distribution agent."""
    click_ctx.obj = AstraContext(
        config_dir=config_dir,
        json_log=json_log,
        verbosity=verbosity,
    )


main.add_command(tenant_group)
main.add_command(run_cmd)
main.add_command(health_cmd)
main.add_command(distribute_cmd)
main.add_command(cadence_group)
main.add_command(auth_group)
main.add_command(events_cmd)
main.add_command(tweets_cmd)


@main.command("version")
def version_cmd() -> None:
    """Print astra-agent version."""
    from astra import __version__
    click.echo(f"astra-agent {__version__}")
