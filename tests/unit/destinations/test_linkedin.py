"""LinkedIn destination tests.

Gate (phase 7): happy path sends 201, extracts x-restli-id; 401/403 set
needs_reauth; 422 records permanent failure; 429/5xx record transient failure;
needs_reauth check skips; claim collision returns skipped; two-tenant isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import respx
from httpx import Response

from astra.config.models import TenantConfig
from astra.db import Database, migrate
from astra.db.repos import (
    DestinationStateRepo,
    DistributionRecordsRepo,
    PublishEventsRepo,
    TenantsRepo,
)
from astra.destinations.linkedin import LinkedInOrgDestination
from astra.domain import PublishEvent, PublishFailure, PublishSkipped, PublishSuccess

if TYPE_CHECKING:
    from pathlib import Path

_LI_URL = "https://api.linkedin.com/rest/posts"


def _tenant(tenant_id: str = "acme") -> TenantConfig:
    return TenantConfig.model_validate({
        "id": tenant_id,
        "name": "Acme",
        "enabled": True,
        "source": {
            "type": "wordpress",
            "url": "https://blog.example.com",
            "username": "admin",
            "app_password_env": "WP_APP_PASSWORD",
        },
        "destinations": {
            "linkedin": {
                "enabled": True,
                "organization_id": "12345",
                "access_token_env": "LINKEDIN_TOKEN",
            }
        },
        "cadences": [],
    })


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "astra.sqlite")
    await database.connect()
    await migrate(database)
    await TenantsRepo(database).upsert("acme", "Acme", enabled=True)
    await TenantsRepo(database).upsert("beta", "Beta", enabled=True)
    try:
        yield database
    finally:
        await database.close()


async def _seed_event(db: Database, tenant_id: str = "acme") -> PublishEvent:
    repo = PublishEventsRepo(db)
    rec = await repo.insert_if_new(
        tenant_id=tenant_id,
        source_name="wordpress",
        source_post_id="p1",
        title="Hello World",
        url="https://blog.example.com/hello",
        excerpt="Short excerpt",
        published_at="2026-01-01T00:00:00Z",
    )
    assert rec is not None
    return PublishEvent(
        tenant_id=tenant_id,
        source_name="wordpress",
        source_post_id="p1",
        title="Hello World",
        url="https://blog.example.com/hello",
        excerpt="Short excerpt",
        published_at="2026-01-01T00:00:00Z",
        db_id=rec.id,
    )


# ── Happy path ───────────────────────────────────────────────────

@respx.mock
async def test_publish_201_returns_success(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(
        return_value=Response(201, headers={"x-restli-id": "urn:li:share:99"})
    )
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "Great post!", db, access_token="tok")

    assert isinstance(result, PublishSuccess)
    assert result.platform_post_id == "urn:li:share:99"

    rec = await DistributionRecordsRepo(db).get(
        tenant_id="acme", publish_event_id=event.db_id, platform="linkedin"
    )
    assert rec is not None
    assert rec.status == "sent"


# ── Auth failures ────────────────────────────────────────────────

@respx.mock
async def test_publish_401_sets_needs_reauth(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(return_value=Response(401, json={}))
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishFailure)
    assert result.transient is False
    state = await DestinationStateRepo(db).get("acme", "linkedin")
    assert state is not None
    assert state.needs_reauth is True


@respx.mock
async def test_publish_403_sets_needs_reauth(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(return_value=Response(403, json={}))
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishFailure)
    state = await DestinationStateRepo(db).get("acme", "linkedin")
    assert state is not None
    assert state.needs_reauth is True


# ── needs_reauth check skips ─────────────────────────────────────

@respx.mock
async def test_publish_skips_when_needs_reauth(db: Database) -> None:
    event = await _seed_event(db)
    await DestinationStateRepo(db).update("acme", "linkedin", needs_reauth=True)
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishSkipped)
    assert result.reason == "needs_reauth"


# ── 422 permanent ────────────────────────────────────────────────

@respx.mock
async def test_publish_422_permanent_failure(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(return_value=Response(422, json={"error": "malformed"}))
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishFailure)
    assert result.transient is False


# ── Transient failures ───────────────────────────────────────────

@respx.mock
async def test_publish_429_transient(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(return_value=Response(429, json={}))
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishFailure)
    assert result.transient is True


@respx.mock
async def test_publish_503_transient(db: Database) -> None:
    event = await _seed_event(db)
    respx.post(_LI_URL).mock(return_value=Response(503, json={}))
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishFailure)
    assert result.transient is True


# ── Claim collision ──────────────────────────────────────────────

@respx.mock
async def test_publish_skips_on_claim_collision(db: Database) -> None:
    event = await _seed_event(db)
    # Pre-claim the slot.
    await DistributionRecordsRepo(db).claim_pending(
        tenant_id="acme", publish_event_id=event.db_id, platform="linkedin"
    )
    dest = LinkedInOrgDestination()
    result = await dest.publish(_tenant(), event, "copy", db, access_token="tok")

    assert isinstance(result, PublishSkipped)
    assert result.reason == "already_claimed"


# ── Two-tenant isolation ─────────────────────────────────────────

@respx.mock
async def test_publish_two_tenant_isolation(db: Database) -> None:
    """Event from tenant-a must not affect tenant-b records."""
    # seed an event for tenant-a
    event_a = await _seed_event(db, tenant_id="acme")

    # seed an event for tenant-b with same source_post_id
    repo = PublishEventsRepo(db)
    rec_b = await repo.insert_if_new(
        tenant_id="beta",
        source_name="wordpress",
        source_post_id="p1",
        title="Beta post",
        url="https://beta.example/p1",
        excerpt=None,
        published_at="2026-01-01T00:00:00Z",
    )
    assert rec_b is not None
    event_b = PublishEvent(
        tenant_id="beta",
        source_name="wordpress",
        source_post_id="p1",
        title="Beta post",
        url="https://beta.example/p1",
        excerpt=None,
        published_at="2026-01-01T00:00:00Z",
        db_id=rec_b.id,
    )

    respx.post(_LI_URL).mock(
        return_value=Response(201, headers={"x-restli-id": "urn:li:share:ok"})
    )

    dest = LinkedInOrgDestination()
    await dest.publish(_tenant("acme"), event_a, "copy a", db, access_token="tok_a")
    await dest.publish(_tenant("beta"), event_b, "copy b", db, access_token="tok_b")

    a_rec = await DistributionRecordsRepo(db).get(
        tenant_id="acme", publish_event_id=event_a.db_id, platform="linkedin"
    )
    b_rec = await DistributionRecordsRepo(db).get(
        tenant_id="beta", publish_event_id=event_b.db_id, platform="linkedin"
    )
    assert a_rec is not None and b_rec is not None
    assert a_rec.tenant_id == "acme"
    assert b_rec.tenant_id == "beta"
    # Cross-query must return nothing.
    cross = await DistributionRecordsRepo(db).get(
        tenant_id="acme", publish_event_id=event_b.db_id, platform="linkedin"
    )
    assert cross is None
