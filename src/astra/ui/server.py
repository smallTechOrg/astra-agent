"""Astra UI FastAPI application factory.

Per spec/product/10-ui-dashboard.md:
- Serves pre-built Next.js static export from astra/ui/out/ via StaticFiles.
- Exposes a JSON API under /api/.
- Session auth via signed cookie (itsdangerous, managed by SessionMiddleware).
- No-auth dev mode when ASTRA_UI_PASSWORD is unset on loopback.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from astra.db import Database, migrate
from astra.db.repos import (
    DestinationStateRepo,
    PromptsRepo,
    PublishEventsRepo,
    TenantConfigRepo,
    TenantSecretsRepo,
    TenantsRepo,
)
from astra.ui.auth import derive_session_key
from astra.ui.auth import router as auth_router
from astra.ui.csrf import verify_csrf
from astra.ui.deps import get_db, require_session

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = logging.getLogger(__name__)

_OUT_DIR = Path(__file__).parent / "out"

# ── app factory ───────────────────────────────────────────────────


def create_app(
    db_url: str,
    ui_password: str | None,
    *,
    loopback: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_url: PostgreSQL DSN.
        ui_password: Value of ASTRA_UI_PASSWORD, or None for no-auth dev mode.
        loopback: Whether the server is bound to loopback (127.0.0.1 / ::1).
    """
    no_auth = ui_password is None and loopback

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        db = Database(db_url)
        await db.connect()
        await migrate(db)
        app.state.db = db
        app.state.ui_password = ui_password
        app.state.no_auth = no_auth
        if no_auth:
            log.warning(
                "astra-ui starting in no-auth dev mode — "
                "set ASTRA_UI_PASSWORD to require a password"
            )
        yield
        await db.close()

    app = FastAPI(title="Astra UI", lifespan=lifespan)

    session_key = derive_session_key(ui_password) if ui_password else secrets.token_hex(32)
    app.add_middleware(SessionMiddleware, secret_key=session_key)

    app.include_router(auth_router)
    _register_api(app)

    if _OUT_DIR.is_dir():
        app.mount("/", StaticFiles(directory=_OUT_DIR, html=True), name="static")

    return app


# ── API routes ────────────────────────────────────────────────────


def _register_api(app: FastAPI) -> None:
    """Register all read-only JSON API endpoints."""

    @app.get("/api/tenants", dependencies=[Depends(require_session)])
    async def list_tenants(db: Database = Depends(get_db)) -> list[dict[str, Any]]:
        rows = await TenantsRepo(db).list_all()
        result = []
        for row in rows:
            cfg = await TenantConfigRepo(db).get(row["id"])
            result.append({
                "id": row["id"],
                "name": row["name"],
                "enabled": row["enabled"],
                "source_type": cfg.source_type if cfg else None,
                "source_url": cfg.source_url if cfg else None,
                "linkedin_enabled": cfg.linkedin_enabled if cfg else False,
                "twitter_enabled": cfg.twitter_enabled if cfg else False,
            })
        return result

    @app.get("/api/tenants/{tenant_id}", dependencies=[Depends(require_session)])
    async def get_tenant(
        tenant_id: str,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        row = await TenantsRepo(db).get(tenant_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Tenant not found"})
        cfg = await TenantConfigRepo(db).get(tenant_id)
        dest_states = await DestinationStateRepo(db).list_for_tenant(tenant_id)
        destinations = {
            s.platform: {
                "needs_reauth": s.needs_reauth,
                "degraded": s.degraded,
                "last_error": s.last_error,
                "updated_at": s.updated_at.isoformat(),
            }
            for s in dest_states
        }
        # Per spec/product/10-ui-dashboard.md#secret-handling-rules:
        # API returns presence only ("set" | "empty"), never values.
        secret_keys = await TenantSecretsRepo(db).list_keys(tenant_id)
        secrets_presence = {k: "set" for k in secret_keys}
        _ALL_SECRET_KEYS = [
            "WP_APP_PASSWORD", "LINKEDIN_ACCESS_TOKEN",
            "TWITTER_API_KEY", "TWITTER_API_SECRET",
            "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
        ]
        for k in _ALL_SECRET_KEYS:
            if k not in secrets_presence:
                secrets_presence[k] = "empty"
        return JSONResponse({
            "id": row["id"],
            "name": row["name"],
            "enabled": row["enabled"],
            "config": {
                "source_type": cfg.source_type,
                "source_url": cfg.source_url,
                "source_username": cfg.source_username,
                "source_poll_cron": cfg.source_poll_cron,
                "linkedin_enabled": cfg.linkedin_enabled,
                "linkedin_org_id": cfg.linkedin_org_id,
                "twitter_enabled": cfg.twitter_enabled,
            } if cfg else None,
            "destinations": destinations,
            "secrets": secrets_presence,
        })

    @app.get("/api/health", dependencies=[Depends(require_session)])
    async def health(db: Database = Depends(get_db)) -> dict[str, Any]:
        rows = await TenantsRepo(db).list_all()
        tenants_health = []
        for row in rows:
            dest_states = await DestinationStateRepo(db).list_for_tenant(row["id"])
            tenants_health.append({
                "id": row["id"],
                "enabled": row["enabled"],
                "destinations": {
                    s.platform: {
                        "needs_reauth": s.needs_reauth,
                        "degraded": s.degraded,
                    }
                    for s in dest_states
                },
            })
        from astra.db.repos import DaemonHeartbeatRepo

        hb = await DaemonHeartbeatRepo(db).get()
        return {
            "daemon": {
                "online": hb is not None,
                "started_at": hb.started_at.isoformat() if hb else None,
                "version": hb.version if hb else None,
                "tenant_count": hb.tenant_count if hb else 0,
                "job_count": hb.job_count if hb else 0,
            },
            "tenants": tenants_health,
        }

    @app.get("/api/events", dependencies=[Depends(require_session)])
    async def list_events(
        tenant: str,
        limit: int = 20,
        db: Database = Depends(get_db),
    ) -> list[dict[str, Any]]:
        events = await PublishEventsRepo(db).list_recent(tenant_id=tenant, limit=limit)
        result = []
        for ev in events:
            dist_rows = await db.fetch_all(
                """
                SELECT platform, status, platform_post_id, error, attempted_at
                FROM distribution_records
                WHERE tenant_id = $1 AND publish_event_id = $2
                """,
                tenant, ev.id,
            )
            result.append({
                "id": ev.id,
                "tenant_id": ev.tenant_id,
                "source_name": ev.source_name,
                "source_post_id": ev.source_post_id,
                "title": ev.title,
                "url": ev.url,
                "published_at": ev.published_at.isoformat(),
                "detected_at": ev.detected_at.isoformat(),
                "distribution": [
                    {
                        "platform": r["platform"],
                        "status": r["status"],
                        "platform_post_id": r["platform_post_id"],
                        "error": r["error"],
                        "attempted_at": r["attempted_at"].isoformat(),
                    }
                    for r in dist_rows
                ],
            })
        return result

    # ── Prompt endpoints per spec/product/10-ui-dashboard.md#prompt-editor ──

    @app.get("/api/prompts", dependencies=[Depends(require_session)])
    async def list_prompts(
        tenant_id: str | None = None,
        scope: str | None = None,
        db: Database = Depends(get_db),
    ) -> list[dict[str, Any]]:
        repo = PromptsRepo(db)
        if scope == "operator":
            records = await repo.list_operator()
        elif tenant_id is not None:
            records = await repo.list_for_tenant(tenant_id)
        else:
            records = await repo.list_operator()
        return [
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "name": r.name,
                "content": r.content,
                "scope": "operator" if r.tenant_id is None else "tenant",
                "updated_at": r.updated_at.isoformat(),
            }
            for r in records
        ]

    @app.get("/api/prompts/{name}", dependencies=[Depends(require_session)])
    async def get_prompt(
        name: str,
        tenant_id: str | None = None,
        scope: str | None = None,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        repo = PromptsRepo(db)
        if scope == "operator":
            record = await repo.get_operator(name)
        elif tenant_id is not None:
            record = await repo.resolve(tenant_id, name)
        else:
            record = await repo.get_operator(name)
        if record is None:
            return JSONResponse(status_code=404, content={"detail": "Prompt not found"})
        return JSONResponse({
            "id": record.id,
            "tenant_id": record.tenant_id,
            "name": record.name,
            "content": record.content,
            "scope": "operator" if record.tenant_id is None else "tenant",
            "updated_at": record.updated_at.isoformat(),
        })

    @app.put("/api/prompts/{name}", dependencies=[Depends(require_session)])
    async def upsert_prompt(
        name: str,
        request: Request,
        tenant_id: str | None = None,
        scope: str | None = None,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        body = await request.json()
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return JSONResponse(
                status_code=422,
                content={"detail": "content is required and must be non-empty"},
            )
        repo = PromptsRepo(db)
        if scope == "operator" or tenant_id is None:
            await repo.upsert_operator(name, content)
        else:
            await repo.upsert_tenant(tenant_id, name, content)
        return JSONResponse({"status": "ok"})

    @app.delete("/api/prompts/{name}", dependencies=[Depends(require_session)])
    async def delete_prompt(
        name: str,
        request: Request,
        tenant_id: str | None = None,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        """Delete a tenant prompt override.

        Per spec/product/10-ui-dashboard.md: only tenant overrides can be
        deleted. Operator defaults are not deletable via this endpoint.
        """
        verify_csrf(request)
        if tenant_id is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "DELETE requires tenant_id — operator defaults cannot be deleted"},
            )
        repo = PromptsRepo(db)
        deleted = await repo.delete_tenant(tenant_id, name)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": "Prompt not found"})
        return JSONResponse({"status": "ok"})
