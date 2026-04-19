"""Astra UI FastAPI application factory.

Per spec/product/10-ui-dashboard.md:
- Serves pre-built Next.js static export from astra/ui/out/ via StaticFiles.
- Exposes a self-sufficient JSON API under /api/ — full CRUD for all entities.
- Session auth via signed cookie (itsdangerous, managed by SessionMiddleware).
- No-auth dev mode when ASTRA_UI_PASSWORD is unset on loopback.
"""

from __future__ import annotations

import logging
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from astra.db import Database, migrate
from astra.db.repos import (
    CadencesRepo,
    DaemonHeartbeatRepo,
    DestinationStateRepo,
    OperatorConfigRepo,
    OperatorSecretsRepo,
    PromptsRepo,
    PublishEventsRepo,
    ScheduledTweetsRepo,
    TenantConfigRepo,
    TenantSecretsRepo,
    TenantsRepo,
)
from astra.ui.auth import derive_session_key
from astra.ui.auth import router as auth_router
from astra.ui.csrf import CSRF_COOKIE, generate_csrf_token, verify_csrf
from astra.ui.deps import get_db, require_session

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = logging.getLogger(__name__)

_OUT_DIR = Path(__file__).parent / "out"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_PROMPT_NAME_RE = re.compile(r"^[a-z0-9_]+$")

_ALL_TENANT_SECRET_KEYS = [
    "WP_APP_PASSWORD", "LINKEDIN_ACCESS_TOKEN",
    "TWITTER_API_KEY", "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
]

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

    # Set CSRF cookie on every response so the frontend can read it.
    class CSRFCookieMiddleware(BaseHTTPMiddleware):
        async def dispatch(  # type: ignore[no-untyped-def]
            self, request: Request, call_next,  # noqa: ANN001
        ):
            response = await call_next(request)
            if CSRF_COOKIE not in request.cookies:
                response.set_cookie(
                    CSRF_COOKIE,
                    generate_csrf_token(),
                    httponly=False,  # JS must read it
                    samesite="strict",
                    path="/",
                )
            return response

    app.add_middleware(CSRFCookieMiddleware)

    app.include_router(auth_router)
    _register_api(app)

    if _OUT_DIR.is_dir():
        # Serve /_next/* static assets directly.
        next_dir = _OUT_DIR / "_next"
        if next_dir.is_dir():
            app.mount("/_next", StaticFiles(directory=next_dir), name="next-static")

        # Catch-all: serve pre-rendered HTML pages from the Next.js export.
        # StaticFiles(html=True) mounted at "/" has issues resolving sub-paths
        # like /login → login.html, so we use an explicit route instead.
        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str) -> FileResponse:
            # Try exact file first (e.g. favicon.ico)
            candidate = _OUT_DIR / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            # Try .html (e.g. /login → login.html)
            html_candidate = _OUT_DIR / (full_path + ".html")
            if html_candidate.is_file():
                return FileResponse(html_candidate, media_type="text/html")
            # Try directory index (e.g. /tenants/new → tenants/new.html)
            index_candidate = _OUT_DIR / full_path / "index.html"
            if index_candidate.is_file():
                return FileResponse(index_candidate, media_type="text/html")
            # Fallback to index.html (SPA client-side routing)
            return FileResponse(_OUT_DIR / "index.html", media_type="text/html")

    return app


# ── API routes ────────────────────────────────────────────────────


def _register_api(app: FastAPI) -> None:  # noqa: C901, PLR0915
    """Register all JSON API endpoints per spec/product/10-ui-dashboard.md."""

    # ── Operator config ───────────────────────────────────────

    @app.get("/api/operator/config", dependencies=[Depends(require_session)])
    async def get_operator_config(db: Database = Depends(get_db)) -> JSONResponse:
        record = await OperatorConfigRepo(db).get()
        if record is None:
            return JSONResponse(status_code=500, content={"detail": "operator_config missing"})
        return JSONResponse({
            "llm_provider": record.llm_provider,
            "llm_model": record.llm_model,
            "llm_temperature": record.llm_temperature,
            "llm_max_tokens": record.llm_max_tokens,
            "log_level": record.log_level,
            "share_sweep_cron": record.share_sweep_cron,
            "startup_grace_seconds": record.startup_grace_seconds,
            "updated_at": record.updated_at.isoformat(),
        })

    @app.put("/api/operator/config", dependencies=[Depends(require_session)])
    async def update_operator_config(
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        body = await request.json()
        allowed = {
            "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
            "log_level", "share_sweep_cron", "startup_grace_seconds",
        }
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            return JSONResponse(status_code=422, content={"detail": "No valid fields provided"})
        await OperatorConfigRepo(db).update(**updates)
        return JSONResponse({"status": "ok"})

    # ── Operator secrets ──────────────────────────────────────

    @app.get("/api/operator/secrets", dependencies=[Depends(require_session)])
    async def get_operator_secrets(db: Database = Depends(get_db)) -> JSONResponse:
        repo = OperatorSecretsRepo(db)
        keys = await repo.list_keys()
        presence: dict[str, str] = {k: "set" for k in keys}
        for k in ("LLM_API_KEY", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
            if k not in presence:
                presence[k] = "empty"
        return JSONResponse(presence)

    @app.put("/api/operator/secrets/{key}", dependencies=[Depends(require_session)])
    async def set_operator_secret(
        key: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        if key not in OperatorSecretsRepo._KNOWN_KEYS:
            return JSONResponse(status_code=400, content={"detail": f"Unknown key: {key}"})
        body = await request.json()
        value = body.get("value")
        if not isinstance(value, str) or not value.strip():
            return JSONResponse(status_code=422, content={"detail": "value is required"})
        await OperatorSecretsRepo(db).set(key, value.strip())
        return JSONResponse({"status": "ok"})

    @app.delete("/api/operator/secrets/{key}", dependencies=[Depends(require_session)])
    async def delete_operator_secret(
        key: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        deleted = await OperatorSecretsRepo(db).delete(key)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": "Secret not found"})
        return JSONResponse({"status": "ok"})

    # ── Tenants (list + detail) ───────────────────────────────

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
        for k in _ALL_TENANT_SECRET_KEYS:
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
                "twitter_announcement_prompt": cfg.twitter_announcement_prompt,
                "llm_provider": cfg.llm_provider,
                "llm_model": cfg.llm_model,
                "llm_temperature": cfg.llm_temperature,
                "llm_max_tokens": cfg.llm_max_tokens,
            } if cfg else None,
            "destinations": destinations,
            "secrets": secrets_presence,
        })

    # ── Tenant CRUD (create, update, delete) ──────────────────

    @app.post("/api/tenants", dependencies=[Depends(require_session)])
    async def create_tenant(
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        body = await request.json()
        tenant_id = body.get("id", "")
        name = body.get("name", "")
        if not isinstance(tenant_id, str) or not _SLUG_RE.match(tenant_id):
            return JSONResponse(
                status_code=422,
                content={"detail": "id must match [a-z0-9][a-z0-9-]*[a-z0-9]"},
            )
        if not isinstance(name, str) or not name.strip():
            return JSONResponse(status_code=422, content={"detail": "name is required"})

        existing = await TenantsRepo(db).get(tenant_id)
        if existing is not None:
            return JSONResponse(status_code=409, content={"detail": "Tenant already exists"})

        await TenantsRepo(db).upsert(tenant_id, name.strip(), enabled=False)
        await TenantConfigRepo(db).upsert(tenant_id)
        return JSONResponse({"id": tenant_id, "name": name.strip(), "enabled": False}, status_code=201)

    @app.put("/api/tenants/{tenant_id}", dependencies=[Depends(require_session)])
    async def update_tenant(
        tenant_id: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        row = await TenantsRepo(db).get(tenant_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Tenant not found"})
        body = await request.json()
        name = body.get("name", row["name"])
        enabled = body.get("enabled", row["enabled"])
        await TenantsRepo(db).upsert(tenant_id, name, enabled)
        return JSONResponse({"id": tenant_id, "name": name, "enabled": enabled})

    @app.delete("/api/tenants/{tenant_id}", dependencies=[Depends(require_session)])
    async def delete_tenant(
        tenant_id: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        row = await TenantsRepo(db).get(tenant_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Tenant not found"})
        await TenantsRepo(db).delete(tenant_id)
        return JSONResponse({"status": "ok"})

    # ── Tenant config ─────────────────────────────────────────

    @app.get("/api/tenants/{tenant_id}/config", dependencies=[Depends(require_session)])
    async def get_tenant_config(
        tenant_id: str,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        cfg = await TenantConfigRepo(db).get(tenant_id)
        if cfg is None:
            return JSONResponse(status_code=404, content={"detail": "tenant_config not found"})
        return JSONResponse({
            "tenant_id": cfg.tenant_id,
            "source_type": cfg.source_type,
            "source_url": cfg.source_url,
            "source_username": cfg.source_username,
            "source_poll_cron": cfg.source_poll_cron,
            "linkedin_enabled": cfg.linkedin_enabled,
            "linkedin_org_id": cfg.linkedin_org_id,
            "linkedin_prompt": cfg.linkedin_prompt,
            "twitter_enabled": cfg.twitter_enabled,
            "twitter_announcement_prompt": cfg.twitter_announcement_prompt,
            "llm_provider": cfg.llm_provider,
            "llm_model": cfg.llm_model,
            "llm_temperature": cfg.llm_temperature,
            "llm_max_tokens": cfg.llm_max_tokens,
            "updated_at": cfg.updated_at.isoformat(),
        })

    @app.put("/api/tenants/{tenant_id}/config", dependencies=[Depends(require_session)])
    async def update_tenant_config(
        tenant_id: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        existing = await TenantConfigRepo(db).get(tenant_id)
        if existing is None:
            return JSONResponse(status_code=404, content={"detail": "tenant_config not found"})
        body = await request.json()
        allowed = {
            "source_type", "source_url", "source_username", "source_poll_cron",
            "linkedin_enabled", "linkedin_org_id", "linkedin_prompt",
            "twitter_enabled", "twitter_announcement_prompt",
            "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
        }
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            return JSONResponse(status_code=422, content={"detail": "No valid fields provided"})
        # Merge with existing values for the full upsert.
        merged = {
            "source_type": existing.source_type,
            "source_url": existing.source_url,
            "source_username": existing.source_username,
            "source_poll_cron": existing.source_poll_cron,
            "linkedin_enabled": existing.linkedin_enabled,
            "linkedin_org_id": existing.linkedin_org_id,
            "linkedin_prompt": existing.linkedin_prompt,
            "twitter_enabled": existing.twitter_enabled,
            "twitter_announcement_prompt": existing.twitter_announcement_prompt,
            "llm_provider": existing.llm_provider,
            "llm_model": existing.llm_model,
            "llm_temperature": existing.llm_temperature,
            "llm_max_tokens": existing.llm_max_tokens,
        }
        merged.update(updates)
        await TenantConfigRepo(db).upsert(tenant_id, **merged)  # type: ignore[arg-type]
        return JSONResponse({"status": "ok"})

    # ── Tenant secrets ────────────────────────────────────────

    @app.get("/api/tenants/{tenant_id}/secrets", dependencies=[Depends(require_session)])
    async def get_tenant_secrets(
        tenant_id: str,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        keys = await TenantSecretsRepo(db).list_keys(tenant_id)
        presence: dict[str, str] = {k: "set" for k in keys}
        for k in _ALL_TENANT_SECRET_KEYS:
            if k not in presence:
                presence[k] = "empty"
        return JSONResponse(presence)

    @app.put("/api/tenants/{tenant_id}/secrets/{key}", dependencies=[Depends(require_session)])
    async def set_tenant_secret(
        tenant_id: str,
        key: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        body = await request.json()
        value = body.get("value")
        if not isinstance(value, str) or not value.strip():
            return JSONResponse(status_code=422, content={"detail": "value is required"})
        await TenantSecretsRepo(db).set(tenant_id, key, value.strip())
        return JSONResponse({"status": "ok"})

    @app.delete("/api/tenants/{tenant_id}/secrets/{key}", dependencies=[Depends(require_session)])
    async def delete_tenant_secret(
        tenant_id: str,
        key: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        await TenantSecretsRepo(db).delete(tenant_id, key)
        return JSONResponse({"status": "ok"})

    # ── Cadences ──────────────────────────────────────────────

    @app.get("/api/tenants/{tenant_id}/cadences", dependencies=[Depends(require_session)])
    async def list_cadences(
        tenant_id: str,
        db: Database = Depends(get_db),
    ) -> list[dict[str, Any]]:
        records = await CadencesRepo(db).list_for_tenant(tenant_id)
        return [
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "name": r.name,
                "cron": r.cron,
                "prompt": r.prompt,
                "feedback_last_n": r.feedback_last_n,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in records
        ]

    @app.post("/api/tenants/{tenant_id}/cadences", dependencies=[Depends(require_session)])
    async def create_cadence(
        tenant_id: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        body = await request.json()
        name = body.get("name", "")
        cron = body.get("cron", "")
        prompt = body.get("prompt", "")
        if not isinstance(name, str) or not _SLUG_RE.match(name):
            return JSONResponse(
                status_code=422,
                content={"detail": "name must match [a-z0-9][a-z0-9-]*[a-z0-9]"},
            )
        if not isinstance(cron, str) or len(cron.split()) != 5:
            return JSONResponse(status_code=422, content={"detail": "cron must be a 5-field expression"})
        if not isinstance(prompt, str) or not prompt.strip():
            return JSONResponse(status_code=422, content={"detail": "prompt is required"})
        feedback_last_n = body.get("feedback_last_n", 20)
        enabled = body.get("enabled", True)

        existing = await CadencesRepo(db).get(tenant_id, name)
        if existing is not None:
            return JSONResponse(status_code=409, content={"detail": "Cadence already exists"})

        await CadencesRepo(db).upsert(
            tenant_id, name=name, cron=cron, prompt=prompt,
            feedback_last_n=feedback_last_n, enabled=enabled,
        )
        return JSONResponse({"status": "ok", "name": name}, status_code=201)

    @app.put("/api/tenants/{tenant_id}/cadences/{name}", dependencies=[Depends(require_session)])
    async def update_cadence(
        tenant_id: str,
        name: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        existing = await CadencesRepo(db).get(tenant_id, name)
        if existing is None:
            return JSONResponse(status_code=404, content={"detail": "Cadence not found"})
        body = await request.json()
        cron = body.get("cron", existing.cron)
        prompt = body.get("prompt", existing.prompt)
        feedback_last_n = body.get("feedback_last_n", existing.feedback_last_n)
        enabled = body.get("enabled", existing.enabled)
        await CadencesRepo(db).upsert(
            tenant_id, name=name, cron=cron, prompt=prompt,
            feedback_last_n=feedback_last_n, enabled=enabled,
        )
        return JSONResponse({"status": "ok"})

    @app.delete("/api/tenants/{tenant_id}/cadences/{name}", dependencies=[Depends(require_session)])
    async def delete_cadence(
        tenant_id: str,
        name: str,
        request: Request,
        db: Database = Depends(get_db),
    ) -> JSONResponse:
        verify_csrf(request)
        await CadencesRepo(db).delete(tenant_id, name)
        return JSONResponse({"status": "ok"})

    # ── Health / daemon ───────────────────────────────────────

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

    # ── Events ────────────────────────────────────────────────

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

    # ── Scheduled tweets ──────────────────────────────────────

    @app.get("/api/tenants/{tenant_id}/tweets", dependencies=[Depends(require_session)])
    async def list_tweets(
        tenant_id: str,
        cadence: str | None = None,
        limit: int = 20,
        db: Database = Depends(get_db),
    ) -> list[dict[str, Any]]:
        records = await ScheduledTweetsRepo(db).list_recent(
            tenant_id, cadence_name=cadence, limit=limit,
        )
        return [
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "cadence_name": r.cadence_name,
                "text": r.text,
                "status": r.status,
                "error": r.error,
                "posted_at": r.posted_at.isoformat(),
            }
            for r in records
        ]

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
