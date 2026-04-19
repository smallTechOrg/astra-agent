"""Session auth routes for the Astra UI.

POST /api/login  — check password, set signed session cookie.
POST /api/logout — clear session.

Session cookie is managed by Starlette's SessionMiddleware (itsdangerous
underneath). The signing key is derived from ASTRA_UI_PASSWORD via SHA-256
so the raw password is never used as a cookie-signing key directly.
Per spec/product/10-ui-dashboard.md#auth.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


def derive_session_key(ui_password: str) -> str:
    """Derive a 64-char hex signing key from the UI password."""
    return hashlib.sha256(b"astra-ui-session:" + ui_password.encode()).hexdigest()


@router.post("/api/login")
async def login(body: LoginRequest, request: Request) -> JSONResponse:
    ui_password: str | None = request.app.state.ui_password
    if ui_password is None:
        request.session["authenticated"] = True
        return JSONResponse({"ok": True})

    if body.password != ui_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    request.session["authenticated"] = True
    return JSONResponse({"ok": True})


@router.post("/api/logout")
async def logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})
