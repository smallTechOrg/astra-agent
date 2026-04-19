"""CSRF token generation and verification.

Double-submit cookie pattern: the server sets a random token in a cookie;
state-changing endpoints require the same value in X-CSRF-Token header.
Wired into endpoint handlers in phase 5.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

CSRF_COOKIE = "astra_csrf"
CSRF_HEADER = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def verify_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF check failed")
