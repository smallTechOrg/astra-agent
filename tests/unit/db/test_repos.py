"""Tenant-scoped repository tests.

Gate (reports/2026-04-17-v0.1-greenfield-implementation.md, phase 2):
- Two-tenant isolation: tenant A's rows never appear in tenant B queries.
- Concurrent insert on `publish_events` with same
  (tenant_id, source_name, source_post_id) — one succeeds, other is swallowed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from astra.db.repos import (
    DestinationStateRepo,
    DistributionRecordsRepo,
    PublishEventsRepo,
    ScheduledTweetsRepo,
    SourceStateRepo,
    TenantsRepo,
)

if TYPE_CHECKING:
    from astra.db import Database

_PUB_AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def db(db: Database) -> Database:
    # Seed two tenants for isolation tests.
    tenants = TenantsRepo(db)
    await tenants.upsert("tenant-a", "Tenant A", enabled=True)
    await tenants.upsert("tenant-b", "Tenant B", enabled=True)
    return db


# ── publish_events ──────────────────────────────────────────────


async def test_publish_event_insert_is_idempotent(db: Database) -> None:
    repo = PublishEventsRepo(db)
    first = await repo.insert_if_new(
        tenant_id="tenant-a",
        source_name="wp",
        source_post_id="post-1",
        title="Hello",
        url="https://example.com/1",
        excerpt=None,
        published_at=_PUB_AT,
    )
    second = await repo.insert_if_new(
        tenant_id="tenant-a",
        source_name="wp",
        source_post_id="post-1",
        title="Hello again",
        url="https://example.com/1",
        excerpt=None,
        published_at=_PUB_AT,
    )

    assert first is not None
    assert second is None  # UNIQUE collision swallowed
    # Original row survives unchanged.
    existing = await repo.get_by_source_id("tenant-a", "wp", "post-1")
    assert existing is not None
    assert existing.title == "Hello"


async def test_publish_events_tenant_isolation(db: Database) -> None:
    repo = PublishEventsRepo(db)
    await repo.insert_if_new(
        tenant_id="tenant-a",
        source_name="wp",
        source_post_id="post-a",
        title="A post",
        url="https://a.example/1",
        excerpt=None,
        published_at=_PUB_AT,
    )
    await repo.insert_if_new(
        tenant_id="tenant-b",
        source_name="wp",
        source_post_id="post-b",
        title="B post",
        url="https://b.example/1",
        excerpt=None,
        published_at=_PUB_AT,
    )

    a_rows = await repo.list_recent("tenant-a")
    b_rows = await repo.list_recent("tenant-b")

    assert [e.source_post_id for e in a_rows] == ["post-a"]
    assert [e.source_post_id for e in b_rows] == ["post-b"]
    # Cross-tenant fetch returns nothing, even for existing source_post_id
    assert await repo.get_by_source_id("tenant-a", "wp", "post-b") is None
    assert await repo.get_by_source_id("tenant-b", "wp", "post-a") is None


async def test_publish_events_same_post_id_allowed_across_tenants(db: Database) -> None:
    repo = PublishEventsRepo(db)
    a = await repo.insert_if_new(
        tenant_id="tenant-a",
        source_name="wp",
        source_post_id="shared-id",
        title="A",
        url="https://a.example/x",
        excerpt=None,
        published_at=_PUB_AT,
    )
    b = await repo.insert_if_new(
        tenant_id="tenant-b",
        source_name="wp",
        source_post_id="shared-id",
        title="B",
        url="https://b.example/x",
        excerpt=None,
        published_at=_PUB_AT,
    )

    assert a is not None and b is not None
    assert a.id != b.id


async def test_publish_events_concurrent_insert(db: Database) -> None:
    """One coroutine inserts, the other is swallowed — exactly one row."""

    repo = PublishEventsRepo(db)

    async def ins() -> object:
        return await repo.insert_if_new(
            tenant_id="tenant-a",
            source_name="wp",
            source_post_id="race",
            title="Race",
            url="https://a.example/race",
            excerpt=None,
            published_at=_PUB_AT,
        )

    results = await asyncio.gather(*(ins() for _ in range(5)))
    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]

    assert len(winners) == 1
    assert len(losers) == 4

    rows = await repo.list_recent("tenant-a")
    assert len(rows) == 1


# ── distribution_records ────────────────────────────────────────


async def test_claim_pending_is_single_winner(db: Database) -> None:
    pubs = PublishEventsRepo(db)
    event = await pubs.insert_if_new(
        tenant_id="tenant-a",
        source_name="wp",
        source_post_id="p",
        title="t",
        url="u",
        excerpt=None,
        published_at=_PUB_AT,
    )
    assert event is not None

    repo = DistributionRecordsRepo(db)
    first = await repo.claim_pending(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    second = await repo.claim_pending(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )

    assert first is not None
    assert first.status == "pending"
    assert second is None


async def test_distribution_tenant_isolation(db: Database) -> None:
    pubs = PublishEventsRepo(db)
    a = await pubs.insert_if_new(
        tenant_id="tenant-a", source_name="wp", source_post_id="p1",
        title="t", url="u", excerpt=None, published_at=_PUB_AT,
    )
    b = await pubs.insert_if_new(
        tenant_id="tenant-b", source_name="wp", source_post_id="p1",
        title="t", url="u", excerpt=None, published_at=_PUB_AT,
    )
    assert a is not None and b is not None

    repo = DistributionRecordsRepo(db)
    await repo.claim_pending(
        tenant_id="tenant-a", publish_event_id=a.id, platform="twitter"
    )
    await repo.claim_pending(
        tenant_id="tenant-b", publish_event_id=b.id, platform="twitter"
    )
    await repo.complete(
        tenant_id="tenant-a", publish_event_id=a.id, platform="twitter",
        status="failed", error="nope",
    )

    a_retry = await repo.list_retryable("tenant-a")
    b_retry = await repo.list_retryable("tenant-b")
    a_pending = await repo.count_pending("tenant-a")
    b_pending = await repo.count_pending("tenant-b")

    assert [r.publish_event_id for r in a_retry] == [a.id]
    assert b_retry == []
    # tenant-a has one failed (counts toward pending-or-failed), tenant-b one pending
    assert a_pending == 1
    assert b_pending == 1
    # Cross-tenant `get` returns None even for an event that belongs to the OTHER tenant
    assert await repo.get(
        tenant_id="tenant-a", publish_event_id=b.id, platform="twitter"
    ) is None


async def test_replace_on_retry_only_resets_failed_rows(db: Database) -> None:
    pubs = PublishEventsRepo(db)
    event = await pubs.insert_if_new(
        tenant_id="tenant-a", source_name="wp", source_post_id="p",
        title="t", url="u", excerpt=None, published_at=_PUB_AT,
    )
    assert event is not None

    repo = DistributionRecordsRepo(db)
    await repo.claim_pending(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    # Not failed yet — retry is a no-op.
    await repo.replace_on_retry(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    row = await repo.get(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    assert row is not None
    assert row.status == "pending"

    # Mark failed, then retry → back to pending with cleared error.
    await repo.complete(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin",
        status="failed", error="boom",
    )
    await repo.replace_on_retry(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    row = await repo.get(
        tenant_id="tenant-a", publish_event_id=event.id, platform="linkedin"
    )
    assert row is not None
    assert row.status == "pending"
    assert row.error is None


# ── source_state / destination_state ────────────────────────────


async def test_source_state_upsert_and_isolation(db: Database) -> None:
    repo = SourceStateRepo(db)
    ts_a = datetime(2026, 1, 1, tzinfo=UTC)
    ts_b = datetime(2026, 1, 2, tzinfo=UTC)

    await repo.upsert("tenant-a", "wp", last_seen_at=ts_a)
    await repo.upsert("tenant-b", "wp", last_seen_at=ts_b)

    a = await repo.get("tenant-a", "wp")
    b = await repo.get("tenant-b", "wp")
    assert a is not None and b is not None
    assert a.last_seen_at == ts_a
    assert b.last_seen_at == ts_b

    # Partial upsert preserves prior values.
    ts_a2 = datetime(2026, 1, 3, tzinfo=UTC)
    await repo.upsert("tenant-a", "wp", last_polled_at=ts_a2)
    a2 = await repo.get("tenant-a", "wp")
    assert a2 is not None
    assert a2.last_seen_at == ts_a  # preserved
    assert a2.last_polled_at == ts_a2


async def test_destination_state_update_and_isolation(db: Database) -> None:
    repo = DestinationStateRepo(db)
    await repo.update(
        "tenant-a", "twitter",
        degraded=True, last_error="rate limited",
    )
    await repo.update("tenant-b", "twitter", needs_reauth=True)

    a = await repo.get("tenant-a", "twitter")
    b = await repo.get("tenant-b", "twitter")
    assert a is not None and b is not None
    assert a.degraded is True
    assert a.last_error == "rate limited"
    assert a.needs_reauth is False
    assert b.needs_reauth is True
    assert b.degraded is False


# ── scheduled_tweets ────────────────────────────────────────────


async def test_scheduled_tweets_isolation(db: Database) -> None:
    repo = ScheduledTweetsRepo(db)
    await repo.insert(
        tenant_id="tenant-a", cadence_name="hourly",
        text="A tweet", platform_post_id="aaa", status="sent",
    )
    await repo.insert(
        tenant_id="tenant-b", cadence_name="hourly",
        text="B tweet", platform_post_id="bbb", status="sent",
    )

    a_sent = await repo.list_recent_sent("tenant-a", "hourly", limit=10)
    b_sent = await repo.list_recent_sent("tenant-b", "hourly", limit=10)

    assert [t.platform_post_id for t in a_sent] == ["aaa"]
    assert [t.platform_post_id for t in b_sent] == ["bbb"]


# ── tenants ─────────────────────────────────────────────────────


async def test_tenants_list_all_is_cross_tenant_by_design(db: Database) -> None:
    repo = TenantsRepo(db)
    rows = await repo.list_all()
    ids = [row["id"] for row in rows]
    assert ids == ["tenant-a", "tenant-b"]


async def test_tenants_delete_cascades(db: Database) -> None:
    pubs = PublishEventsRepo(db)
    event = await pubs.insert_if_new(
        tenant_id="tenant-a", source_name="wp", source_post_id="p",
        title="t", url="u", excerpt=None, published_at=_PUB_AT,
    )
    assert event is not None

    await TenantsRepo(db).delete("tenant-a")

    rows = await pubs.list_recent("tenant-a")
    assert rows == []
