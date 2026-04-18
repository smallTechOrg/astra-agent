"""astra auth — OAuth flows for destinations.

Per spec/product/06-cli.md#auth.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.cli.context import AstraContext


@click.group("auth")
def auth_group() -> None:
    """Authenticate with external services."""


@auth_group.command("linkedin")
@click.option("--tenant", "tenant_id", required=True, metavar="ID")
@click.option("--client-id", required=True, metavar="ID")
@click.option("--client-secret", required=True, metavar="SECRET")
@click.option("--port", default=8989, show_default=True, help="Local callback port.")
@click.pass_obj
def linkedin_auth(
    ctx: AstraContext,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    port: int,
) -> None:
    """Run LinkedIn OAuth2 flow and write token to tenant_secrets table."""
    import asyncio

    exit_code = asyncio.run(_run_linkedin_auth(ctx, tenant_id, client_id, client_secret, port))
    sys.exit(exit_code)


async def _run_linkedin_auth(
    ctx: AstraContext,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    port: int,
) -> int:
    from astra.db import Database, migrate
    from astra.db.repos import TenantSecretsRepo, TenantsRepo

    database_url = ctx.database_url
    async with Database(database_url) as db:
        await migrate(db)
        tenant_row = await TenantsRepo(db).get(tenant_id)
        if tenant_row is None:
            click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
            return 1

        redirect_uri = f"http://localhost:{port}/callback"
        auth_url = (
            "https://www.linkedin.com/oauth/v2/authorization"
            "?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            "&scope=w_member_social%20r_organization_social"
        )

        click.echo("Open this URL in your browser to authorise:")
        click.echo(f"  {auth_url}")
        click.echo(f"Listening on http://localhost:{port}/callback ...")

        code = await _listen_for_code(port)
        if not code:
            click.echo("Error: did not receive auth code.", err=True)
            return 2

        token = await _exchange_code(client_id, client_secret, code, redirect_uri)
        if not token:
            click.echo("Error: token exchange failed.", err=True)
            return 2

        await TenantSecretsRepo(db).set(tenant_id, "LINKEDIN_ACCESS_TOKEN", token)

    click.echo(f"LinkedIn access token saved to DB for tenant {tenant_id!r}.")
    click.echo("Restart the daemon to clear needs_reauth status.")
    return 0


async def _listen_for_code(port: int) -> str | None:
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    result: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if "code" in params:
                result.append(params["code"][0])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Auth complete. You can close this tab.")
            threading.Thread(target=self.server.shutdown).start()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("localhost", port), _Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    for _ in range(120):
        await asyncio.sleep(1)
        if result:
            break

    return result[0] if result else None


async def _exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str | None:
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if resp.status_code != 200:
            return None
        return str(resp.json().get("access_token", ""))
