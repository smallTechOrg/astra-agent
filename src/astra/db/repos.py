"""Tenant-scoped repository helpers.

Every query routes through a helper here to make P1 (tenant_id in every
predicate) a *structural* property, not a discipline one. See
spec/engineering/tenant-isolation.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from astra.db.connection import Database


def utc_now() -> str:
    """ISO-8601 UTC now with Z suffix (DB's canonical timestamp format)."""

    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── tenants ─────────────────────────────────────────────────────

class TenantsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, tenant_id: str, name: str, enabled: bool) -> None:
        now = utc_now()
        async for conn in self._db.iter_writes():
            await conn.execute(
                """
                INSERT INTO tenants (id, name, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, name, 1 if enabled else 0, now, now),
            )

    async def delete(self, tenant_id: str) -> None:
        await self._db.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))

    async def list_all(self) -> list[aiosqlite.Row]:
        """Operator-level cross-tenant read. Used only by CLI listings."""

        return await self._db.fetch_all("SELECT * FROM tenants ORDER BY id")


# ── source_state ────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceState:
    tenant_id: str
    source_name: str
    last_seen_at: str | None
    last_polled_at: str | None
    needs_reauth: bool


class SourceStateRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str, source_name: str) -> SourceState | None:
        row = await self._db.fetch_one(
            "SELECT * FROM source_state WHERE tenant_id = ? AND source_name = ?",
            (tenant_id, source_name),
        )
        if row is None:
            return None
        return SourceState(
            tenant_id=row["tenant_id"],
            source_name=row["source_name"],
            last_seen_at=row["last_seen_at"],
            last_polled_at=row["last_polled_at"],
            needs_reauth=bool(row["needs_reauth"]),
        )

    async def upsert(
        self,
        tenant_id: str,
        source_name: str,
        *,
        last_seen_at: str | None = None,
        last_polled_at: str | None = None,
        needs_reauth: bool | None = None,
    ) -> None:
        current = await self.get(tenant_id, source_name)
        effective_last_seen = last_seen_at if last_seen_at is not None else (
            current.last_seen_at if current else None
        )
        effective_polled = last_polled_at if last_polled_at is not None else (
            current.last_polled_at if current else None
        )
        effective_reauth = needs_reauth if needs_reauth is not None else (
            current.needs_reauth if current else False
        )
        async for conn in self._db.iter_writes():
            await conn.execute(
                """
                INSERT INTO source_state
                    (tenant_id, source_name, last_seen_at, last_polled_at, needs_reauth)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, source_name) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    last_polled_at = excluded.last_polled_at,
                    needs_reauth = excluded.needs_reauth
                """,
                (
                    tenant_id,
                    source_name,
                    effective_last_seen,
                    effective_polled,
                    1 if effective_reauth else 0,
                ),
            )


# ── destination_state ───────────────────────────────────────────

@dataclass(frozen=True)
class DestinationState:
    tenant_id: str
    platform: str
    needs_reauth: bool
    degraded: bool
    last_error: str | None
    rate_limit_reset_at: str | None
    updated_at: str


class DestinationStateRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str, platform: str) -> DestinationState | None:
        row = await self._db.fetch_one(
            "SELECT * FROM destination_state WHERE tenant_id = ? AND platform = ?",
            (tenant_id, platform),
        )
        if row is None:
            return None
        return DestinationState(
            tenant_id=row["tenant_id"],
            platform=row["platform"],
            needs_reauth=bool(row["needs_reauth"]),
            degraded=bool(row["degraded"]),
            last_error=row["last_error"],
            rate_limit_reset_at=row["rate_limit_reset_at"],
            updated_at=row["updated_at"],
        )

    async def update(
        self,
        tenant_id: str,
        platform: str,
        *,
        needs_reauth: bool | None = None,
        degraded: bool | None = None,
        last_error: str | None = None,
        rate_limit_reset_at: str | None = None,
    ) -> None:
        current = await self.get(tenant_id, platform)
        now = utc_now()
        effective_reauth = needs_reauth if needs_reauth is not None else (
            current.needs_reauth if current else False
        )
        effective_degraded = degraded if degraded is not None else (
            current.degraded if current else False
        )
        effective_error = last_error if last_error is not None else (
            current.last_error if current else None
        )
        effective_reset = rate_limit_reset_at if rate_limit_reset_at is not None else (
            current.rate_limit_reset_at if current else None
        )
        async for conn in self._db.iter_writes():
            await conn.execute(
                """
                INSERT INTO destination_state
                    (tenant_id, platform, needs_reauth, degraded, last_error,
                     rate_limit_reset_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, platform) DO UPDATE SET
                    needs_reauth = excluded.needs_reauth,
                    degraded = excluded.degraded,
                    last_error = excluded.last_error,
                    rate_limit_reset_at = excluded.rate_limit_reset_at,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id,
                    platform,
                    1 if effective_reauth else 0,
                    1 if effective_degraded else 0,
                    effective_error,
                    effective_reset,
                    now,
                ),
            )


# ── publish_events ──────────────────────────────────────────────

@dataclass(frozen=True)
class PublishEventRecord:
    id: int
    tenant_id: str
    source_name: str
    source_post_id: str
    title: str
    url: str
    excerpt: str | None
    published_at: str
    detected_at: str


class PublishEventsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_if_new(
        self,
        *,
        tenant_id: str,
        source_name: str,
        source_post_id: str,
        title: str,
        url: str,
        excerpt: str | None,
        published_at: str,
    ) -> PublishEventRecord | None:
        """Idempotent insert. Returns the row if inserted, else None."""

        detected_at = utc_now()
        try:
            async for conn in self._db.iter_writes():
                await conn.execute(
                    """
                    INSERT INTO publish_events
                        (tenant_id, source_name, source_post_id, title, url,
                         excerpt, published_at, detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        source_name,
                        source_post_id,
                        title,
                        url,
                        excerpt,
                        published_at,
                        detected_at,
                    ),
                )
        except aiosqlite.IntegrityError:
            return None

        row = await self._db.fetch_one(
            """
            SELECT * FROM publish_events
            WHERE tenant_id = ? AND source_name = ? AND source_post_id = ?
            """,
            (tenant_id, source_name, source_post_id),
        )
        if row is None:  # pragma: no cover — race impossible after successful insert
            return None
        return _row_to_publish_event(row)

    async def get_by_source_id(
        self, tenant_id: str, source_name: str, source_post_id: str
    ) -> PublishEventRecord | None:
        row = await self._db.fetch_one(
            """
            SELECT * FROM publish_events
            WHERE tenant_id = ? AND source_name = ? AND source_post_id = ?
            """,
            (tenant_id, source_name, source_post_id),
        )
        return _row_to_publish_event(row) if row else None

    async def get_by_id(self, publish_event_id: int) -> PublishEventRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM publish_events WHERE id = ?",
            (publish_event_id,),
        )
        return _row_to_publish_event(row) if row else None

    async def list_recent(
        self, tenant_id: str, limit: int = 20
    ) -> list[PublishEventRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM publish_events
            WHERE tenant_id = ?
            ORDER BY detected_at DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        )
        return [_row_to_publish_event(row) for row in rows]


def _row_to_publish_event(row: aiosqlite.Row) -> PublishEventRecord:
    return PublishEventRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        source_name=row["source_name"],
        source_post_id=row["source_post_id"],
        title=row["title"],
        url=row["url"],
        excerpt=row["excerpt"],
        published_at=row["published_at"],
        detected_at=row["detected_at"],
    )


# ── distribution_records ────────────────────────────────────────

@dataclass(frozen=True)
class DistributionRecord:
    id: int
    tenant_id: str
    publish_event_id: int
    platform: str
    status: str
    platform_post_id: str | None
    copy: str | None
    error: str | None
    attempted_at: str
    completed_at: str | None


class DistributionRecordsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def claim_pending(
        self,
        *,
        tenant_id: str,
        publish_event_id: int,
        platform: str,
    ) -> DistributionRecord | None:
        """Insert a pending row. Returns None if another runner already claimed it."""

        attempted_at = utc_now()
        try:
            async for conn in self._db.iter_writes():
                await conn.execute(
                    """
                    INSERT INTO distribution_records
                        (tenant_id, publish_event_id, platform, status, attempted_at)
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (tenant_id, publish_event_id, platform, attempted_at),
                )
        except aiosqlite.IntegrityError:
            return None
        return await self.get(tenant_id=tenant_id, publish_event_id=publish_event_id, platform=platform)

    async def complete(
        self,
        *,
        tenant_id: str,
        publish_event_id: int,
        platform: str,
        status: str,
        platform_post_id: str | None = None,
        copy: str | None = None,
        error: str | None = None,
    ) -> None:
        completed_at = utc_now()
        await self._db.execute(
            """
            UPDATE distribution_records
            SET status = ?, platform_post_id = ?, copy = ?, error = ?, completed_at = ?
            WHERE tenant_id = ? AND publish_event_id = ? AND platform = ?
            """,
            (
                status,
                platform_post_id,
                copy,
                error,
                completed_at,
                tenant_id,
                publish_event_id,
                platform,
            ),
        )

    async def replace_on_retry(
        self,
        *,
        tenant_id: str,
        publish_event_id: int,
        platform: str,
    ) -> None:
        """Reset a failed row to pending for retry (spec invariant 5)."""

        await self._db.execute(
            """
            UPDATE distribution_records
            SET status = 'pending', error = NULL, completed_at = NULL,
                platform_post_id = NULL, attempted_at = ?
            WHERE tenant_id = ? AND publish_event_id = ? AND platform = ? AND status = 'failed'
            """,
            (utc_now(), tenant_id, publish_event_id, platform),
        )

    async def get(
        self, *, tenant_id: str, publish_event_id: int, platform: str
    ) -> DistributionRecord | None:
        row = await self._db.fetch_one(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = ? AND publish_event_id = ? AND platform = ?
            """,
            (tenant_id, publish_event_id, platform),
        )
        return _row_to_distribution(row) if row else None

    async def list_for_event(
        self, tenant_id: str, publish_event_id: int
    ) -> list[DistributionRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = ? AND publish_event_id = ?
            """,
            (tenant_id, publish_event_id),
        )
        return [_row_to_distribution(row) for row in rows]

    async def list_retryable(self, tenant_id: str) -> list[DistributionRecord]:
        """Rows that the share-sweep should revisit (failed with transient error)."""

        rows = await self._db.fetch_all(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = ? AND status = 'failed'
            ORDER BY attempted_at ASC
            """,
            (tenant_id,),
        )
        return [_row_to_distribution(row) for row in rows]

    async def count_pending(self, tenant_id: str) -> int:
        row = await self._db.fetch_one(
            """
            SELECT COUNT(*) AS c FROM distribution_records
            WHERE tenant_id = ? AND status IN ('pending', 'failed')
            """,
            (tenant_id,),
        )
        return int(row["c"]) if row else 0


def _row_to_distribution(row: aiosqlite.Row) -> DistributionRecord:
    return DistributionRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        publish_event_id=row["publish_event_id"],
        platform=row["platform"],
        status=row["status"],
        platform_post_id=row["platform_post_id"],
        copy=row["copy"],
        error=row["error"],
        attempted_at=row["attempted_at"],
        completed_at=row["completed_at"],
    )


# ── scheduled_tweets ────────────────────────────────────────────

@dataclass(frozen=True)
class ScheduledTweetRecord:
    id: int
    tenant_id: str
    cadence_name: str
    text: str | None
    platform_post_id: str | None
    status: str
    error: str | None
    posted_at: str


class ScheduledTweetsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        tenant_id: str,
        cadence_name: str,
        text: str | None,
        platform_post_id: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO scheduled_tweets
                (tenant_id, cadence_name, text, platform_post_id, status, error, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                cadence_name,
                text,
                platform_post_id,
                status,
                error,
                utc_now(),
            ),
        )

    async def list_recent_sent(
        self, tenant_id: str, cadence_name: str, limit: int
    ) -> list[ScheduledTweetRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM scheduled_tweets
            WHERE tenant_id = ? AND cadence_name = ? AND status = 'sent'
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (tenant_id, cadence_name, limit),
        )
        return [_row_to_scheduled_tweet(row) for row in rows]

    async def list_recent(
        self, tenant_id: str, cadence_name: str | None = None, limit: int = 20
    ) -> list[ScheduledTweetRecord]:
        if cadence_name is not None:
            rows = await self._db.fetch_all(
                """
                SELECT * FROM scheduled_tweets
                WHERE tenant_id = ? AND cadence_name = ?
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                (tenant_id, cadence_name, limit),
            )
        else:
            rows = await self._db.fetch_all(
                """
                SELECT * FROM scheduled_tweets
                WHERE tenant_id = ?
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            )
        return [_row_to_scheduled_tweet(row) for row in rows]


def _row_to_scheduled_tweet(row: aiosqlite.Row) -> ScheduledTweetRecord:
    return ScheduledTweetRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        cadence_name=row["cadence_name"],
        text=row["text"],
        platform_post_id=row["platform_post_id"],
        status=row["status"],
        error=row["error"],
        posted_at=row["posted_at"],
    )
