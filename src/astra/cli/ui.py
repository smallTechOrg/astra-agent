"""astra ui — start the operator web dashboard.

Per spec/product/06-cli.md#ui-server and spec/product/10-ui-dashboard.md.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


@click.command("ui")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
@click.option("--port", default=8080, show_default=True, help="Bind port.")
@click.option("--open", "open_browser", is_flag=True, help="Open browser after startup.")
@click.pass_obj
def ui_cmd(ctx: AstraContext, host: str, port: int, open_browser: bool) -> None:
    """Start the operator web UI."""
    from astra.config.secrets import load_dotenv_file
    from astra.logging import configure_logging
    from astra.ui.server import create_app

    cfg = ctx.load_config()
    log_level = "debug" if ctx.verbosity > 0 else cfg.operator.log_level
    configure_logging(json=ctx.json_log, level=log_level)

    env = load_dotenv_file(ctx.config_dir / ".env")
    ui_password = env.get("ASTRA_UI_PASSWORD")
    loopback = host in _LOOPBACK

    # Per spec: refuse to start with non-loopback host unless password is set.
    if not loopback and not ui_password:
        click.echo(
            "Error: ASTRA_UI_PASSWORD must be set in config/.env "
            "when binding to a non-loopback address.",
            err=True,
        )
        sys.exit(1)

    app = create_app(
        db_url=cfg.database_url,
        ui_password=ui_password,
        loopback=loopback,
    )

    if open_browser:
        import threading
        import webbrowser

        url = f"http://{host}:{port}"
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    import uvicorn

    uvicorn.run(app, host=host, port=port)
