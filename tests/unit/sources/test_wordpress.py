"""WordPressSource unit tests.

Gate (phase 6 from plan): registry resolves wordpress type, poll() inserts
events and advances last_seen_at, idempotent on duplicate post_id, auth/5xx/
429/bad-json failure modes don't update state, two-tenant isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import respx
from httpx import ConnectError, Response

from astra.config.models import TenantConfig
from astra.db.repos import SourceStateRepo, TenantsRepo
from astra.sources import WordPressSource, get_source
from astra.sources.base import Source

if TYPE_CHECKING:
    from astra.db import Database

_WP_BASE = "https://blog.example.com"
_WP_URL = f"{_WP_BASE}/wp-json/wp/v2/posts"


def _tenant(tenant_id: str = "acme") -> TenantConfig:
    return TenantConfig.model_validate({
        "id": tenant_id,
        "name": "Acme",
        "enabled": True,
        "source": {
            "type": "wordpress",
            "url": _WP_BASE,
            "username": "admin",
        },
        "destinations": {},
        "cadences": [],
    })


def _post(post_id: int, date_gmt: str = "2026-01-01T10:00:00") -> dict[object, object]:
    """WordPress date_gmt is without timezone suffix: %Y-%m-%dT%H:%M:%S."""
    return {
        "id": post_id,
        "title": {"rendered": f"Post {post_id}"},
        "link": f"{_WP_BASE}/post-{post_id}/",
        "excerpt": {"rendered": f"<p>Excerpt {post_id}</p>"},
        "date_gmt": date_gmt,
    }


@pytest.fixture
async def db(db: Database) -> Database:
    await TenantsRepo(db).upsert("acme", "Acme", enabled=True)
    await TenantsRepo(db).upsert("beta", "Beta", enabled=True)
    return db


# ── Registry ─────────────────────────────────────────────────────

def test_registry_resolves_wordpress() -> None:
    cls = get_source("wordpress")
    assert issubclass(cls, Source)
    assert cls is WordPressSource


def test_registry_unknown_raises() -> None:
    from astra.errors import UnknownSourceTypeError
    from astra.sources.registry import get_source as _get

    with pytest.raises(UnknownSourceTypeError):
        _get("nonexistent_source_type")


# ── Happy path ───────────────────────────────────────────────────

@respx.mock
async def test_poll_inserts_new_events(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(
        return_value=Response(200, json=[_post(1), _post(2)])
    )
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")

    assert len(events) == 2
    assert {e.source_post_id for e in events} == {"1", "2"}
    assert all(e.tenant_id == "acme" for e in events)


@respx.mock
async def test_poll_advances_last_seen_at(db: Database) -> None:
    from datetime import UTC, datetime

    respx.get(url__startswith=_WP_URL).mock(
        return_value=Response(200, json=[
            _post(1, "2026-01-01T08:00:00"),
            _post(2, "2026-01-01T09:00:00"),
        ])
    )
    source = WordPressSource()
    await source.poll(_tenant(), db, app_password="secret")

    state = await SourceStateRepo(db).get("acme", "wordpress")
    assert state is not None
    assert state.last_seen_at == datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    assert state.last_polled_at is not None


@respx.mock
async def test_poll_idempotent_on_duplicate_post(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(
        return_value=Response(200, json=[_post(1)])
    )
    source = WordPressSource()
    first = await source.poll(_tenant(), db, app_password="secret")
    second = await source.poll(_tenant(), db, app_password="secret")

    assert len(first) == 1
    assert len(second) == 0  # already seen; no new event


@respx.mock
async def test_poll_empty_response_returns_empty(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(return_value=Response(200, json=[]))
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")
    assert events == []


# ── Failure modes ────────────────────────────────────────────────

@respx.mock
async def test_poll_401_returns_empty_does_not_update_state(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(return_value=Response(401, json={}))
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="bad")

    assert events == []
    state = await SourceStateRepo(db).get("acme", "wordpress")
    assert state is None or state.last_seen_at is None


@respx.mock
async def test_poll_429_returns_empty_does_not_update_state(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(return_value=Response(429, json={}))
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")

    assert events == []


@respx.mock
async def test_poll_bad_json_returns_empty(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(
        return_value=Response(200, content=b"NOT JSON")
    )
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")

    assert events == []


@respx.mock
async def test_poll_connection_error_returns_empty(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(side_effect=ConnectError("no route"))
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")

    assert events == []


@respx.mock
async def test_poll_5xx_retries_then_succeeds(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(
        side_effect=[
            Response(503, json={}),
            Response(503, json={}),
            Response(200, json=[_post(99)]),
        ]
    )
    source = WordPressSource()
    events = await source.poll(_tenant(), db, app_password="secret")

    assert len(events) == 1
    assert events[0].source_post_id == "99"


# ── Two-tenant isolation ─────────────────────────────────────────

@respx.mock
async def test_two_tenants_events_are_isolated(db: Database) -> None:
    respx.get(url__startswith=_WP_URL).mock(
        return_value=Response(200, json=[_post(1)])
    )
    source = WordPressSource()
    a_events = await source.poll(_tenant("acme"), db, app_password="secret")
    b_events = await source.poll(_tenant("beta"), db, app_password="secret")

    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0].tenant_id == "acme"
    assert b_events[0].tenant_id == "beta"
    # DB IDs differ — they are separate rows.
    assert a_events[0].db_id != b_events[0].db_id
