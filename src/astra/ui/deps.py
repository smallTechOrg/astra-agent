"""FastAPI dependency providers for the Astra UI.

Per spec/product/10-ui-dashboard.md#auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from astra.db.connection import Database


async def get_db(request: Request) -> Database:
    """Yield the shared DB pool stored in app state during lifespan."""
    return request.app.state.db  # type: ignore[no-any-return]


async def require_session(request: Request) -> None:
    """Block unauthenticated requests to protected API routes.

    Skipped entirely when the app runs in no-auth dev mode
    (ASTRA_UI_PASSWORD unset on loopback).
    """
    if getattr(request.app.state, "no_auth", False):
        return
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
