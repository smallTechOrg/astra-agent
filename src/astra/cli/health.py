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
    cfg = ctx.load_config()
    db_path = ctx.config_dir.parent / cfg.operator.database_path
    any_failed = False

    # Operator-level checks.
    if tenant_id is None:
        click.echo("Operator")
        db_ok = db_path.exists() or True  # DB is created on daemon start; file may not exist yet
        click.echo(f"  Database:       {'ok' if db_ok else 'FAILED'}")

        llm_status = await _check_llm(cfg.operator.llm)
        click.echo(f"  LLM ({cfg.operator.llm.provider}):{'':>5}{llm_status}")
        if "FAILED" in llm_status:
            any_failed = True
        click.echo("")

    tenants_to_check = (
        {tenant_id: cfg.tenants[tenant_id]} if tenant_id and tenant_id in cfg.tenants
        else cfg.tenants
    )

    if tenant_id and tenant_id not in cfg.tenants:
        click.echo(f"Error: tenant {tenant_id!r} not found.", err=True)
        return 1

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
            li_status = await _check_linkedin(loaded.config, secrets)
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


async def _check_llm(llm_cfg: object) -> str:
    import os

    from astra.config.models import LLMConfig
    assert isinstance(llm_cfg, LLMConfig)
    api_key = os.environ.get(llm_cfg.api_key_env, "")
    if not api_key:
        return f"FAILED — missing {llm_cfg.api_key_env}"
    return "ok (key present, not tested)"


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


async def _check_linkedin(tenant_cfg: object, secrets: Mapping[str, SecretStr]) -> str:
    from astra.config.models import TenantConfig
    assert isinstance(tenant_cfg, TenantConfig)
    env_var = tenant_cfg.destinations.linkedin.access_token_env
    token_secret: SecretStr | None = secrets.get(env_var)
    if not token_secret:
        return f"FAILED — missing {env_var}"
    from astra.destinations import get_destination
    dest = get_destination("linkedin")()
    result = await dest.health_check(tenant_cfg, access_token=token_secret.get_secret_value())
    if result.ok:
        return "ok"
    if result.needs_reauth:
        return f"FAILED — needs_reauth (run: astra auth linkedin --tenant {tenant_cfg.id})"
    return f"FAILED — {result.reason}"


async def _check_twitter(tenant_cfg: object, secrets: Mapping[str, SecretStr]) -> str:
    from astra.config.models import TenantConfig
    assert isinstance(tenant_cfg, TenantConfig)
    tw = tenant_cfg.destinations.twitter

    def _get(env_var: str) -> str:
        s: SecretStr | None = secrets.get(env_var)
        return s.get_secret_value() if s else ""

    packed = "|".join([
        _get(tw.api_key_env),
        _get(tw.api_secret_env),
        _get(tw.access_token_env),
        _get(tw.access_secret_env),
    ])
    if packed == "|||":
        return "FAILED — missing credentials"

    from astra.destinations import get_destination
    dest = get_destination("twitter")()
    result = await dest.health_check(tenant_cfg, access_token=packed)
    if result.ok:
        return "ok"
    if result.needs_reauth:
        return "FAILED — needs_reauth"
    return f"FAILED — {result.reason}"
