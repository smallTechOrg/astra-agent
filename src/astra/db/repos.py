"""Tenant-scoped repository helpers.

Every query routes through a helper here to make P1 (tenant_id in every
predicate) a *structural* property, not a discipline one. See
spec/engineering/tenant-isolation.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from astra.db.connection import Database


def _now() -> datetime:
    return datetime.now(UTC)


# ── tenants ──────────────────────────────────────────────────────


class TenantsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, tenant_id: str, name: str, enabled: bool) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO tenants (id, name, enabled, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (id) DO UPDATE SET
                name       = EXCLUDED.name,
                enabled    = EXCLUDED.enabled,
                updated_at = EXCLUDED.updated_at
            """,
            tenant_id, name, enabled, now,
        )

    async def get(self, tenant_id: str) -> asyncpg.Record | None:
        return await self._db.fetch_one(
            "SELECT * FROM tenants WHERE id = $1", tenant_id
        )

    async def delete(self, tenant_id: str) -> None:
        await self._db.execute("DELETE FROM tenants WHERE id = $1", tenant_id)

    async def list_all(self) -> list[asyncpg.Record]:
        """Operator-level cross-tenant read. Used only by CLI listings."""
        return await self._db.fetch_all("SELECT * FROM tenants ORDER BY id")


# ── tenant_config ─────────────────────────────────────────────────


@dataclass
class TenantConfig:
    tenant_id: str
    source_type: str
    source_url: str | None
    source_username: str | None
    source_poll_cron: str
    linkedin_enabled: bool
    linkedin_org_id: str | None
    linkedin_prompt: str
    twitter_enabled: bool
    twitter_announcement_prompt: str
    llm_provider: str | None
    llm_model: str | None
    llm_temperature: float | None
    llm_max_tokens: int | None
    updated_at: datetime


class TenantConfigRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str) -> TenantConfig | None:
        row = await self._db.fetch_one(
            "SELECT * FROM tenant_config WHERE tenant_id = $1", tenant_id
        )
        return _row_to_tenant_config(row) if row else None

    async def upsert(
        self,
        tenant_id: str,
        *,
        source_type: str = "wordpress",
        source_url: str | None = None,
        source_username: str | None = None,
        source_poll_cron: str = "*/5 * * * *",
        linkedin_enabled: bool = False,
        linkedin_org_id: str | None = None,
        linkedin_prompt: str = "linkedin_announcement",
        twitter_enabled: bool = False,
        twitter_announcement_prompt: str = "twitter_announcement",
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_temperature: float | None = None,
        llm_max_tokens: int | None = None,
    ) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO tenant_config (
                tenant_id, source_type, source_url, source_username,
                source_poll_cron, linkedin_enabled, linkedin_org_id,
                linkedin_prompt, twitter_enabled, twitter_announcement_prompt,
                llm_provider, llm_model, llm_temperature, llm_max_tokens,
                updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            ON CONFLICT (tenant_id) DO UPDATE SET
                source_type                 = EXCLUDED.source_type,
                source_url                  = EXCLUDED.source_url,
                source_username             = EXCLUDED.source_username,
                source_poll_cron            = EXCLUDED.source_poll_cron,
                linkedin_enabled            = EXCLUDED.linkedin_enabled,
                linkedin_org_id             = EXCLUDED.linkedin_org_id,
                linkedin_prompt             = EXCLUDED.linkedin_prompt,
                twitter_enabled             = EXCLUDED.twitter_enabled,
                twitter_announcement_prompt = EXCLUDED.twitter_announcement_prompt,
                llm_provider                = EXCLUDED.llm_provider,
                llm_model                   = EXCLUDED.llm_model,
                llm_temperature             = EXCLUDED.llm_temperature,
                llm_max_tokens              = EXCLUDED.llm_max_tokens,
                updated_at                  = EXCLUDED.updated_at
            """,
            tenant_id, source_type, source_url, source_username,
            source_poll_cron, linkedin_enabled, linkedin_org_id,
            linkedin_prompt, twitter_enabled, twitter_announcement_prompt,
            llm_provider, llm_model, llm_temperature, llm_max_tokens, now,
        )


def _row_to_tenant_config(row: asyncpg.Record) -> TenantConfig:
    return TenantConfig(
        tenant_id=row["tenant_id"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        source_username=row["source_username"],
        source_poll_cron=row["source_poll_cron"],
        linkedin_enabled=row["linkedin_enabled"],
        linkedin_org_id=row["linkedin_org_id"],
        linkedin_prompt=row["linkedin_prompt"],
        twitter_enabled=row["twitter_enabled"],
        twitter_announcement_prompt=row["twitter_announcement_prompt"],
        llm_provider=row["llm_provider"],
        llm_model=row["llm_model"],
        llm_temperature=row["llm_temperature"],
        llm_max_tokens=row["llm_max_tokens"],
        updated_at=row["updated_at"],
    )


# ── tenant_secrets ────────────────────────────────────────────────


class TenantSecretsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str, key: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT value FROM tenant_secrets WHERE tenant_id = $1 AND key = $2",
            tenant_id, key,
        )
        return str(row["value"]) if row else None

    async def set(self, tenant_id: str, key: str, value: str) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO tenant_secrets (tenant_id, key, value, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tenant_id, key) DO UPDATE SET
                value      = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            """,
            tenant_id, key, value, now,
        )

    async def delete(self, tenant_id: str, key: str) -> None:
        await self._db.execute(
            "DELETE FROM tenant_secrets WHERE tenant_id = $1 AND key = $2",
            tenant_id, key,
        )

    async def list_keys(self, tenant_id: str) -> list[str]:
        """Returns key names for presence checks — never returns values."""
        rows = await self._db.fetch_all(
            "SELECT key FROM tenant_secrets WHERE tenant_id = $1 ORDER BY key",
            tenant_id,
        )
        return [str(r["key"]) for r in rows]


# ── cadences ──────────────────────────────────────────────────────


@dataclass
class CadenceRecord:
    id: int
    tenant_id: str
    name: str
    cron: str
    prompt: str
    feedback_last_n: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CadencesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_for_tenant(self, tenant_id: str) -> list[CadenceRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM cadences WHERE tenant_id = $1 ORDER BY name",
            tenant_id,
        )
        return [_row_to_cadence(r) for r in rows]

    async def get(self, tenant_id: str, name: str) -> CadenceRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM cadences WHERE tenant_id = $1 AND name = $2",
            tenant_id, name,
        )
        return _row_to_cadence(row) if row else None

    async def upsert(
        self,
        tenant_id: str,
        *,
        name: str,
        cron: str,
        prompt: str,
        feedback_last_n: int = 20,
        enabled: bool = True,
    ) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO cadences
                (tenant_id, name, cron, prompt, feedback_last_n, enabled,
                 created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$7)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                cron            = EXCLUDED.cron,
                prompt          = EXCLUDED.prompt,
                feedback_last_n = EXCLUDED.feedback_last_n,
                enabled         = EXCLUDED.enabled,
                updated_at      = EXCLUDED.updated_at
            """,
            tenant_id, name, cron, prompt, feedback_last_n, enabled, now,
        )

    async def delete(self, tenant_id: str, name: str) -> None:
        await self._db.execute(
            "DELETE FROM cadences WHERE tenant_id = $1 AND name = $2",
            tenant_id, name,
        )


def _row_to_cadence(row: asyncpg.Record) -> CadenceRecord:
    return CadenceRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        cron=row["cron"],
        prompt=row["prompt"],
        feedback_last_n=row["feedback_last_n"],
        enabled=row["enabled"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── source_state ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceState:
    tenant_id: str
    source_name: str
    last_seen_at: datetime | None
    last_polled_at: datetime | None


class SourceStateRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str, source_name: str) -> SourceState | None:
        row = await self._db.fetch_one(
            "SELECT * FROM source_state WHERE tenant_id = $1 AND source_name = $2",
            tenant_id, source_name,
        )
        if row is None:
            return None
        return SourceState(
            tenant_id=row["tenant_id"],
            source_name=row["source_name"],
            last_seen_at=row["last_seen_at"],
            last_polled_at=row["last_polled_at"],
        )

    async def upsert(
        self,
        tenant_id: str,
        source_name: str,
        *,
        last_seen_at: datetime | None = None,
        last_polled_at: datetime | None = None,
    ) -> None:
        current = await self.get(tenant_id, source_name)
        effective_last_seen = last_seen_at if last_seen_at is not None else (
            current.last_seen_at if current else None
        )
        effective_polled = last_polled_at if last_polled_at is not None else (
            current.last_polled_at if current else None
        )
        await self._db.execute(
            """
            INSERT INTO source_state
                (tenant_id, source_name, last_seen_at, last_polled_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tenant_id, source_name) DO UPDATE SET
                last_seen_at   = EXCLUDED.last_seen_at,
                last_polled_at = EXCLUDED.last_polled_at
            """,
            tenant_id, source_name, effective_last_seen, effective_polled,
        )


# ── destination_state ────────────────────────────────────────────


@dataclass(frozen=True)
class DestinationState:
    tenant_id: str
    platform: str
    needs_reauth: bool
    degraded: bool
    last_error: str | None
    updated_at: datetime


class DestinationStateRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: str, platform: str) -> DestinationState | None:
        row = await self._db.fetch_one(
            "SELECT * FROM destination_state WHERE tenant_id = $1 AND platform = $2",
            tenant_id, platform,
        )
        if row is None:
            return None
        return DestinationState(
            tenant_id=row["tenant_id"],
            platform=row["platform"],
            needs_reauth=row["needs_reauth"],
            degraded=row["degraded"],
            last_error=row["last_error"],
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
    ) -> None:
        current = await self.get(tenant_id, platform)
        now = _now()
        effective_reauth = needs_reauth if needs_reauth is not None else (
            current.needs_reauth if current else False
        )
        effective_degraded = degraded if degraded is not None else (
            current.degraded if current else False
        )
        effective_error = last_error if last_error is not None else (
            current.last_error if current else None
        )
        await self._db.execute(
            """
            INSERT INTO destination_state
                (tenant_id, platform, needs_reauth, degraded, last_error, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (tenant_id, platform) DO UPDATE SET
                needs_reauth = EXCLUDED.needs_reauth,
                degraded     = EXCLUDED.degraded,
                last_error   = EXCLUDED.last_error,
                updated_at   = EXCLUDED.updated_at
            """,
            tenant_id, platform, effective_reauth, effective_degraded,
            effective_error, now,
        )

    async def list_for_tenant(self, tenant_id: str) -> list[DestinationState]:
        rows = await self._db.fetch_all(
            "SELECT * FROM destination_state WHERE tenant_id = $1", tenant_id
        )
        return [
            DestinationState(
                tenant_id=r["tenant_id"],
                platform=r["platform"],
                needs_reauth=r["needs_reauth"],
                degraded=r["degraded"],
                last_error=r["last_error"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]


# ── publish_events ───────────────────────────────────────────────


@dataclass(frozen=True)
class PublishEventRecord:
    id: int
    tenant_id: str
    source_name: str
    source_post_id: str
    title: str
    url: str
    excerpt: str | None
    published_at: datetime
    detected_at: datetime


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
        published_at: datetime,
    ) -> PublishEventRecord | None:
        """Idempotent insert. Returns the row if inserted, else None."""
        detected_at = _now()
        try:
            async with self._db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO publish_events
                        (tenant_id, source_name, source_post_id, title, url,
                         excerpt, published_at, detected_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    tenant_id, source_name, source_post_id, title, url,
                    excerpt, published_at, detected_at,
                )
        except asyncpg.UniqueViolationError:
            return None

        return await self.get_by_source_id(tenant_id, source_name, source_post_id)

    async def get_by_source_id(
        self, tenant_id: str, source_name: str, source_post_id: str
    ) -> PublishEventRecord | None:
        row = await self._db.fetch_one(
            """
            SELECT * FROM publish_events
            WHERE tenant_id = $1 AND source_name = $2 AND source_post_id = $3
            """,
            tenant_id, source_name, source_post_id,
        )
        return _row_to_publish_event(row) if row else None

    async def get_by_id(self, publish_event_id: int) -> PublishEventRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM publish_events WHERE id = $1", publish_event_id
        )
        return _row_to_publish_event(row) if row else None

    async def list_recent(
        self, tenant_id: str, limit: int = 20
    ) -> list[PublishEventRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM publish_events
            WHERE tenant_id = $1
            ORDER BY detected_at DESC
            LIMIT $2
            """,
            tenant_id, limit,
        )
        return [_row_to_publish_event(r) for r in rows]


def _row_to_publish_event(row: asyncpg.Record) -> PublishEventRecord:
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


# ── distribution_records ─────────────────────────────────────────


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
    attempted_at: datetime
    completed_at: datetime | None


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
        attempted_at = _now()
        try:
            async with self._db.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO distribution_records
                        (tenant_id, publish_event_id, platform, status, attempted_at)
                    VALUES ($1, $2, $3, 'pending', $4)
                    """,
                    tenant_id, publish_event_id, platform, attempted_at,
                )
        except asyncpg.UniqueViolationError:
            return None
        return await self.get(
            tenant_id=tenant_id,
            publish_event_id=publish_event_id,
            platform=platform,
        )

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
        completed_at = _now()
        await self._db.execute(
            """
            UPDATE distribution_records
            SET status = $1, platform_post_id = $2, copy = $3,
                error = $4, completed_at = $5
            WHERE tenant_id = $6 AND publish_event_id = $7 AND platform = $8
            """,
            status, platform_post_id, copy, error, completed_at,
            tenant_id, publish_event_id, platform,
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
                platform_post_id = NULL, attempted_at = $1
            WHERE tenant_id = $2 AND publish_event_id = $3
              AND platform = $4 AND status = 'failed'
            """,
            _now(), tenant_id, publish_event_id, platform,
        )

    async def get(
        self, *, tenant_id: str, publish_event_id: int, platform: str
    ) -> DistributionRecord | None:
        row = await self._db.fetch_one(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = $1 AND publish_event_id = $2 AND platform = $3
            """,
            tenant_id, publish_event_id, platform,
        )
        return _row_to_distribution(row) if row else None

    async def list_for_event(
        self, tenant_id: str, publish_event_id: int
    ) -> list[DistributionRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = $1 AND publish_event_id = $2
            """,
            tenant_id, publish_event_id,
        )
        return [_row_to_distribution(r) for r in rows]

    async def list_retryable(self, tenant_id: str) -> list[DistributionRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM distribution_records
            WHERE tenant_id = $1 AND status = 'failed'
            ORDER BY attempted_at ASC
            """,
            tenant_id,
        )
        return [_row_to_distribution(r) for r in rows]

    async def count_pending(self, tenant_id: str) -> int:
        val = await self._db.fetch_val(
            """
            SELECT COUNT(*) FROM distribution_records
            WHERE tenant_id = $1 AND status IN ('pending', 'failed')
            """,
            tenant_id,
        )
        return int(val) if val is not None else 0  # type: ignore[call-overload]


def _row_to_distribution(row: asyncpg.Record) -> DistributionRecord:
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


# ── daemon_heartbeat ──────────────────────────────────────────────


@dataclass(frozen=True)
class DaemonHeartbeat:
    started_at: datetime
    version: str
    tenant_count: int
    job_count: int
    updated_at: datetime


class DaemonHeartbeatRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        started_at: datetime,
        version: str,
        tenant_count: int,
        job_count: int,
    ) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO daemon_heartbeat
                (id, started_at, version, tenant_count, job_count, updated_at)
            VALUES (1, $1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                started_at   = EXCLUDED.started_at,
                version      = EXCLUDED.version,
                tenant_count = EXCLUDED.tenant_count,
                job_count    = EXCLUDED.job_count,
                updated_at   = EXCLUDED.updated_at
            """,
            started_at, version, tenant_count, job_count, now,
        )

    async def get(self) -> DaemonHeartbeat | None:
        row = await self._db.fetch_one("SELECT * FROM daemon_heartbeat WHERE id = 1")
        if row is None:
            return None
        return DaemonHeartbeat(
            started_at=row["started_at"],
            version=row["version"],
            tenant_count=row["tenant_count"],
            job_count=row["job_count"],
            updated_at=row["updated_at"],
        )


# ── scheduled_tweets ─────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduledTweetRecord:
    id: int
    tenant_id: str
    cadence_name: str
    text: str | None
    platform_post_id: str | None
    status: str
    error: str | None
    posted_at: datetime


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
                (tenant_id, cadence_name, text, platform_post_id,
                 status, error, posted_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            tenant_id, cadence_name, text, platform_post_id,
            status, error, _now(),
        )

    async def list_recent_sent(
        self, tenant_id: str, cadence_name: str, limit: int
    ) -> list[ScheduledTweetRecord]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM scheduled_tweets
            WHERE tenant_id = $1 AND cadence_name = $2 AND status = 'sent'
            ORDER BY posted_at DESC
            LIMIT $3
            """,
            tenant_id, cadence_name, limit,
        )
        return [_row_to_scheduled_tweet(r) for r in rows]

    async def list_recent(
        self, tenant_id: str, cadence_name: str | None = None, limit: int = 20
    ) -> list[ScheduledTweetRecord]:
        if cadence_name is not None:
            rows = await self._db.fetch_all(
                """
                SELECT * FROM scheduled_tweets
                WHERE tenant_id = $1 AND cadence_name = $2
                ORDER BY posted_at DESC
                LIMIT $3
                """,
                tenant_id, cadence_name, limit,
            )
        else:
            rows = await self._db.fetch_all(
                """
                SELECT * FROM scheduled_tweets
                WHERE tenant_id = $1
                ORDER BY posted_at DESC
                LIMIT $2
                """,
                tenant_id, limit,
            )
        return [_row_to_scheduled_tweet(r) for r in rows]


def _row_to_scheduled_tweet(row: asyncpg.Record) -> ScheduledTweetRecord:
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


# ── prompts ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PromptRecord:
    id: int
    tenant_id: str | None
    name: str
    content: str
    created_at: datetime
    updated_at: datetime


class PromptsRepo:
    """Read/write prompts from the DB.

    Resolution order per spec/product/08-prompts.md: tenant row → operator row.
    Operator rows have tenant_id IS NULL.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def resolve(self, tenant_id: str, name: str) -> PromptRecord | None:
        """Return the tenant override if it exists, else the operator default."""
        row = await self._db.fetch_one(
            """
            SELECT * FROM prompts
            WHERE name = $1 AND (tenant_id = $2 OR tenant_id IS NULL)
            ORDER BY tenant_id IS NULL  -- tenant row first (false < true)
            LIMIT 1
            """,
            name, tenant_id,
        )
        if row is None:
            return None
        return _row_to_prompt(row)

    async def get_operator(self, name: str) -> PromptRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompts WHERE tenant_id IS NULL AND name = $1",
            name,
        )
        return _row_to_prompt(row) if row else None

    async def get_tenant(self, tenant_id: str, name: str) -> PromptRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompts WHERE tenant_id = $1 AND name = $2",
            tenant_id, name,
        )
        return _row_to_prompt(row) if row else None

    async def list_operator(self) -> list[PromptRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompts WHERE tenant_id IS NULL ORDER BY name"
        )
        return [_row_to_prompt(r) for r in rows]

    async def list_for_tenant(self, tenant_id: str) -> list[PromptRecord]:
        """Return all prompts relevant to a tenant — overrides + operator defaults."""
        rows = await self._db.fetch_all(
            """
            SELECT DISTINCT ON (name) *
            FROM prompts
            WHERE tenant_id = $1 OR tenant_id IS NULL
            ORDER BY name, tenant_id IS NULL
            """,
            tenant_id,
        )
        return [_row_to_prompt(r) for r in rows]

    async def list_tenant_overrides(self, tenant_id: str) -> list[PromptRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompts WHERE tenant_id = $1 ORDER BY name",
            tenant_id,
        )
        return [_row_to_prompt(r) for r in rows]

    async def upsert_operator(self, name: str, content: str) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO prompts (tenant_id, name, content, created_at, updated_at)
            VALUES (NULL, $1, $2, $3, $3)
            ON CONFLICT ON CONSTRAINT prompts_tenant_id_name_key DO UPDATE SET
                content    = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
            """,
            name, content, now,
        )

    async def upsert_tenant(self, tenant_id: str, name: str, content: str) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO prompts (tenant_id, name, content, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT ON CONSTRAINT prompts_tenant_id_name_key DO UPDATE SET
                content    = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
            """,
            tenant_id, name, content, now,
        )

    async def delete_tenant(self, tenant_id: str, name: str) -> bool:
        row = await self._db.fetch_one(
            "DELETE FROM prompts WHERE tenant_id = $1 AND name = $2 RETURNING id",
            tenant_id, name,
        )
        return row is not None


def _row_to_prompt(row: asyncpg.Record) -> PromptRecord:
    return PromptRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        content=row["content"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── operator_config ──────────────────────────────────────────────


@dataclass(frozen=True)
class OperatorConfigRecord:
    llm_provider: str
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    log_level: str
    share_sweep_cron: str
    startup_grace_seconds: int
    updated_at: datetime


class OperatorConfigRepo:
    """Singleton operator_config row. Per spec/product/05-config.md."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self) -> OperatorConfigRecord | None:
        row = await self._db.fetch_one("SELECT * FROM operator_config WHERE id = 1")
        if row is None:
            return None
        return OperatorConfigRecord(
            llm_provider=row["llm_provider"],
            llm_model=row["llm_model"],
            llm_temperature=row["llm_temperature"],
            llm_max_tokens=row["llm_max_tokens"],
            log_level=row["log_level"],
            share_sweep_cron=row["share_sweep_cron"],
            startup_grace_seconds=row["startup_grace_seconds"],
            updated_at=row["updated_at"],
        )

    async def update(self, **kwargs: object) -> None:
        """Partial update. Only pass columns to change."""
        allowed = {
            "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
            "log_level", "share_sweep_cron", "startup_grace_seconds",
        }
        to_set = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not to_set:
            return
        to_set["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(to_set))
        values = list(to_set.values())
        await self._db.execute(
            f"UPDATE operator_config SET {set_clause} WHERE id = 1",  # noqa: S608
            *values,
        )


# ── operator_secrets ─────────────────────────────────────────────


class OperatorSecretsRepo:
    """Operator-level secrets. Per spec/product/05-config.md."""

    _KNOWN_KEYS = frozenset({"LLM_API_KEY", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"})

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT value FROM operator_secrets WHERE key = $1", key
        )
        return str(row["value"]) if row else None

    async def set(self, key: str, value: str) -> None:
        now = _now()
        await self._db.execute(
            """
            INSERT INTO operator_secrets (key, value, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE SET
                value      = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            """,
            key, value, now,
        )

    async def delete(self, key: str) -> bool:
        row = await self._db.fetch_one(
            "DELETE FROM operator_secrets WHERE key = $1 RETURNING key", key
        )
        return row is not None

    async def list_keys(self) -> list[str]:
        """Returns key names only — never returns values."""
        rows = await self._db.fetch_all(
            "SELECT key FROM operator_secrets ORDER BY key"
        )
        return [str(r["key"]) for r in rows]
