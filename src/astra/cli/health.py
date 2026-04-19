"""astra health — check service connectivity.

Per spec/product/06-cli.md#health.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import SecretStr

    from astra.cli.context import AstraContext


@click.command("health")
@click.option("--tenant", "tenant_id", default=None, metavar="ID", help="Check only this tenant.")
@click.pass_obj
def health_cmd(ctx: AstraContext, tenant_id: str | None) -> None:
    """Check health of configured services."""
    exit_code = asyncio.run(_run_health(ctx, tenant_id))
    sys.exit(exit_code)


async def _run_health(ctx: AstraContext, tenant_id: str | None) -> int:

    from astra.config.loader import ConfigLoader
    from astra.db import Database, migrate
    from astra.db.repos import OperatorSecretsRepo

    loader = ConfigLoader(ctx.config_dir)
    any_failed = False

    async with Database(ctx.database_url) as db:
        await migrate(db)

        if tenant_id is None:
            click.echo("Operator")
            operator_cfg = await loader.load_operator_from_db(db)
            llm_api_key = await OperatorSecretsRepo(db).get("LLM_API_KEY")
            llm_status = "ok (key present, not tested)" if llm_api_key else "FAILED — LLM_API_KEY not set in operator_secrets"
            click.echo(f"  LLM ({operator_cfg.llm.provider}):{'':>5}{llm_status}")
            if "FAILED" in llm_status:
                any_failed = True
            click.echo("")

        loaded_map = await loader.load_tenants_from_db(db)

    if tenant_id is not None and tenant_id not in loaded_map:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

    tenants_to_check = (
        {tenant_id: loaded_map[tenant_id]}
        if tenant_id
        else loaded_map
    )

    for tid, loaded in tenants_to_check.items():
        click.echo(f"Tenant: {tid}")
        if not loaded.config.enabled:
            click.echo("  (disabled)")
            click.echo("")
            continue
        if loaded.degraded:
            click.echo(f"  DEGRADED — {loaded.degraded_reason}")
            any_failed = True
            click.echo("")
            continue

        secrets = loaded.secrets

        wp_status = await _check_wordpress(loaded.config)
        click.echo(f"  WordPress:      {wp_status}")
        if "FAILED" in wp_status:
            any_failed = True

        if loaded.config.destinations.linkedin.enabled:
            li_status = await _check_linkedin(secrets)
            click.echo(f"  LinkedIn:       {li_status}")
            if "FAILED" in li_status:
                any_failed = True

        if loaded.config.destinations.twitter.enabled:
            tw_status = await _check_twitter(loaded.config, secrets)
            click.echo(f"  Twitter:        {tw_status}")
            if "FAILED" in tw_status:
                any_failed = True

        click.echo("")

    return 2 if any_failed else 0


async def _check_wordpress(tenant_cfg: object) -> str:
    import httpx

    from astra.config.models import TenantConfig
    assert isinstance(tenant_cfg, TenantConfig)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{tenant_cfg.source.url}/wp-json/wp/v2/")
            if resp.status_code == 200:
                return "ok"
            return f"FAILED — HTTP {resp.status_code}"
    except Exception as exc:
        return f"FAILED — {exc}"


async def _check_linkedin(secrets: Mapping[str, SecretStr]) -> str:
    token_secret: SecretStr | None = secrets.get("LINKEDIN_ACCESS_TOKEN")
    if not token_secret:
        return "FAILED — LINKEDIN_ACCESS_TOKEN not set"
    return "ok (token present, not tested)"


async def _check_twitter(tenant_cfg: object, secrets: Mapping[str, SecretStr]) -> str:
    from astra.config.models import TenantConfig
    assert isinstance(tenant_cfg, TenantConfig)

    def _get(key: str) -> str:
        s: SecretStr | None = secrets.get(key)
        return s.get_secret_value() if s else ""

    keys = ["TWITTER_API_KEY", "TWITTER_API_SECRET",
            "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"]
    missing = [k for k in keys if not _get(k)]
    if missing:
        return f"FAILED — missing: {', '.join(missing)}"

    from astra.destinations import get_destination
    dest = get_destination("twitter")()
    packed = "|".join(_get(k) for k in keys)
    result = await dest.health_check(tenant_cfg, access_token=packed)
    if result.ok:
        return "ok"
    if result.needs_reauth:
        return "FAILED — needs_reauth"
    return f"FAILED — {result.reason}"
