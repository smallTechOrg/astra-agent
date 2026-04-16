# Data model

**Status:** DRAFT

SQLite, via `aiosqlite`. Single file at `state/astra.db` by default (configurable via `operator.yaml → database_path`). One database, all tenants. Every non-`tenants` table has a `tenant_id` column and is always queried with `WHERE tenant_id = ?`.

All timestamps are ISO-8601 strings in UTC with `Z` suffix. SQLite doesn't have a native datetime type; string comparison on ISO-8601 is lexicographically correct.

## Schema

```sql
-- ── Tenants ──────────────────────────────────────────────────

CREATE TABLE tenants (
    id           TEXT PRIMARY KEY,              -- slug, from tenant.yaml
    name         TEXT NOT NULL,                 -- display name
    enabled      INTEGER NOT NULL DEFAULT 1,    -- 0 | 1
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- The `tenants` row is upserted at daemon startup from tenant.yaml. The YAML
-- is authoritative for configuration; this table exists so that foreign keys
-- and joins work cleanly. Deleting a row here cascades to all other tables.

-- ── Source state ─────────────────────────────────────────────

CREATE TABLE source_state (
    tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name    TEXT NOT NULL,                 -- e.g. 'wordpress'
    last_seen_at   TEXT,                          -- ISO-8601, nullable on first run
    last_polled_at TEXT,
    needs_reauth   INTEGER NOT NULL DEFAULT 0,    -- applies to destinations; see note
    PRIMARY KEY (tenant_id, source_name)
);

-- Note: `needs_reauth` is on source_state for now. When we add more
-- destinations with their own auth expiry, we split this into a
-- `destination_state` table. See 09-extensibility.md.

CREATE TABLE destination_state (
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform     TEXT NOT NULL,                   -- 'linkedin' | 'twitter'
    needs_reauth INTEGER NOT NULL DEFAULT 0,
    degraded     INTEGER NOT NULL DEFAULT 0,      -- set on non-recoverable errors until reload
    last_error   TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (tenant_id, platform)
);

-- ── Publish events ───────────────────────────────────────────

CREATE TABLE publish_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,                -- 'wordpress'
    source_post_id  TEXT NOT NULL,                -- WP post ID as string (forward-compat)
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    excerpt         TEXT,
    published_at    TEXT NOT NULL,                -- from WP's date_gmt
    detected_at     TEXT NOT NULL,                -- when Astra first saw it
    UNIQUE (tenant_id, source_name, source_post_id)
);

CREATE INDEX idx_publish_events_tenant_detected
    ON publish_events (tenant_id, detected_at DESC);

-- ── Distribution records ─────────────────────────────────────

CREATE TABLE distribution_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    publish_event_id  INTEGER NOT NULL REFERENCES publish_events(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,              -- 'linkedin' | 'twitter'
    status            TEXT NOT NULL,              -- 'pending' | 'sent' | 'failed' | 'skipped'
    platform_post_id  TEXT,                       -- URN / tweet ID, null when not sent
    copy              TEXT,                       -- the actual text we posted (or attempted)
    error             TEXT,                       -- human-readable error on failure
    attempted_at      TEXT NOT NULL,
    completed_at      TEXT,
    UNIQUE (publish_event_id, platform)
);

CREATE INDEX idx_distribution_records_tenant_status
    ON distribution_records (tenant_id, status);

-- ── Scheduled (cadence) tweets ───────────────────────────────

CREATE TABLE scheduled_tweets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cadence_name      TEXT NOT NULL,              -- from tenant.yaml cadences[].name
    text              TEXT,                       -- the actual text posted (null if LLM failed)
    platform_post_id  TEXT,                       -- tweet ID, null if failed/skipped
    status            TEXT NOT NULL,              -- 'sent' | 'failed' | 'skipped'
    error             TEXT,
    posted_at         TEXT NOT NULL
);

CREATE INDEX idx_scheduled_tweets_tenant_cadence_posted
    ON scheduled_tweets (tenant_id, cadence_name, posted_at DESC);
```

## Invariants

These must hold at all times. Any code that violates them is a bug.

1. **Tenant scoping.** Every query against `source_state`, `destination_state`, `publish_events`, `distribution_records`, `scheduled_tweets` includes `WHERE tenant_id = ?`. Unscoped queries exist only for operator reports and must be explicitly reviewed.
2. **Idempotent publish detection.** Two concurrent `publish_events` inserts for the same `(tenant_id, source_name, source_post_id)` cannot both succeed. The loser's `UNIQUE` violation is expected and silently swallowed.
3. **Idempotent distribution.** Two concurrent `distribution_records` inserts for the same `(publish_event_id, platform)` cannot both succeed. The loser exits without calling the platform API.
4. **Status transitions.** `distribution_records.status` moves `pending → sent | failed | skipped`. It never moves backward. `failed` rows may be retried by deleting and re-inserting (the share-sweep does this conditionally — see below), but a `sent` row is terminal.
5. **Retry policy.** The share-sweep (`daemon.share_sweep_cron`) may re-attempt a `failed` distribution by upserting the row (replace on conflict) if the failure was classified as transient (rate-limit, 5xx). Non-transient failures (auth, duplicate content, validation) are not auto-retried.
6. **Monotonic `last_seen_at`.** `source_state.last_seen_at` never moves backward.

## Retention

No automatic pruning in v1. These tables grow unboundedly. For a hobby deployment this is fine for years. A future capability `astra prune --older-than 90d` is out of scope here.

## Migrations

- Schema versioning: a single `schema_version` table with one row, one integer column, updated by migrations.
- Migrations live in code under a `migrations/` module, applied on daemon startup before any other DB access.
- Each migration is forward-only. No downgrade path.
- Adding a column or table: new migration appended.
- Renaming / dropping a column: new migration appended, with a note in this file explaining the semantic change.

## Why not Postgres

We expect <100 tenants and <10K rows per tenant per year. SQLite easily handles 100× that. A single-file DB also means operator backups are `cp state/astra.db backup.db`. If we ever scale past this, swapping in Postgres requires a migration but no schema redesign — the schema is portable.
