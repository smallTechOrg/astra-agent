# Data model

**Status:** DRAFT

PostgreSQL, via `asyncpg`. Connection configured via `DATABASE_URL` in the operator `.env` (e.g. `postgresql://astra:astra@localhost:5432/astra`). One database, all tenants. Every non-`tenants` table has a `tenant_id` column and is always queried with `WHERE tenant_id = $1`.

All timestamps are `TIMESTAMPTZ` in UTC. Native PostgreSQL datetime type; comparisons and ordering are correct by default.

## Schema

```sql
-- ── Tenants ──────────────────────────────────────────────────

CREATE TABLE tenants (
    id           TEXT PRIMARY KEY,              -- slug, set at creation
    name         TEXT NOT NULL,                 -- display name
    enabled      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant configuration ─────────────────────────────────────
-- Replaces per-tenant tenant.yaml. Written by CLI and UI; read by daemon.

CREATE TABLE tenant_config (
    tenant_id               TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    -- Source
    source_type             TEXT NOT NULL DEFAULT 'wordpress',
    source_url              TEXT,
    source_username         TEXT,
    source_poll_cron        TEXT NOT NULL DEFAULT '*/5 * * * *',
    -- LinkedIn destination
    linkedin_enabled        BOOLEAN NOT NULL DEFAULT false,
    linkedin_org_id         TEXT,
    linkedin_prompt         TEXT NOT NULL DEFAULT 'linkedin_announcement',
    -- Twitter destination
    twitter_enabled         BOOLEAN NOT NULL DEFAULT false,
    twitter_announcement_prompt TEXT NOT NULL DEFAULT 'twitter_announcement',
    -- Optional per-tenant LLM override
    llm_provider            TEXT,
    llm_model               TEXT,
    llm_temperature         REAL,
    llm_max_tokens          INTEGER,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant secrets ───────────────────────────────────────────
-- Replaces per-tenant .env files. Values stored plaintext.
-- Known keys: WP_APP_PASSWORD, LINKEDIN_ACCESS_TOKEN,
--             TWITTER_API_KEY, TWITTER_API_SECRET,
--             TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET

CREATE TABLE tenant_secrets (
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

-- ── Cadences ─────────────────────────────────────────────────
-- Replaces cadences[] array in tenant.yaml. One row per cadence job.

CREATE TABLE cadences (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    cron            TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    feedback_last_n INTEGER NOT NULL DEFAULT 20,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- ── Prompts ──────────────────────────────────────────────────
-- Stores prompt content. Rows with tenant_id IS NULL are operator defaults.
-- Rows with a tenant_id are per-tenant overrides.
-- Resolution: tenant row → operator row → error. See 08-prompts.md.

CREATE TABLE prompts (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- Partial unique index for operator-level defaults (tenant_id IS NULL).
CREATE UNIQUE INDEX idx_prompts_operator_default
    ON prompts (name) WHERE tenant_id IS NULL;

-- ── Source state ─────────────────────────────────────────────

CREATE TABLE source_state (
    tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name    TEXT NOT NULL,
    last_seen_at   TIMESTAMPTZ,
    last_polled_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, source_name)
);

CREATE TABLE destination_state (
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform     TEXT NOT NULL,                   -- 'linkedin' | 'twitter'
    needs_reauth BOOLEAN NOT NULL DEFAULT false,
    degraded     BOOLEAN NOT NULL DEFAULT false,
    last_error   TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, platform)
);

-- ── Publish events ───────────────────────────────────────────

CREATE TABLE publish_events (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    source_post_id  TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    excerpt         TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, source_name, source_post_id)
);

CREATE INDEX idx_publish_events_tenant_detected
    ON publish_events (tenant_id, detected_at DESC);

-- ── Distribution records ─────────────────────────────────────

CREATE TABLE distribution_records (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    publish_event_id  BIGINT NOT NULL REFERENCES publish_events(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    status            TEXT NOT NULL,              -- 'pending' | 'sent' | 'failed' | 'skipped'
    platform_post_id  TEXT,
    copy              TEXT,
    error             TEXT,
    attempted_at      TIMESTAMPTZ NOT NULL,
    completed_at      TIMESTAMPTZ,
    UNIQUE (publish_event_id, platform)
);

CREATE INDEX idx_distribution_records_tenant_status
    ON distribution_records (tenant_id, status);

-- ── Daemon heartbeat ────────────────────────────────────────
-- Singleton row written by `astra run` on startup. Read by `astra ui`
-- to determine whether the daemon is running and what it loaded.

CREATE TABLE daemon_heartbeat (
    id           INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    started_at   TIMESTAMPTZ NOT NULL,
    version      TEXT NOT NULL,
    tenant_count INTEGER NOT NULL DEFAULT 0,
    job_count    INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Scheduled (cadence) tweets ───────────────────────────────

CREATE TABLE scheduled_tweets (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cadence_name     TEXT NOT NULL,
    text             TEXT,
    platform_post_id TEXT,
    status           TEXT NOT NULL,              -- 'sent' | 'failed' | 'skipped'
    error            TEXT,
    posted_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_scheduled_tweets_tenant_cadence_posted
    ON scheduled_tweets (tenant_id, cadence_name, posted_at DESC);
```

## Invariants

These must hold at all times. Any code that violates them is a bug.

1. **Tenant scoping.** Every query against `source_state`, `destination_state`, `publish_events`, `distribution_records`, `scheduled_tweets`, `tenant_config`, `tenant_secrets`, `cadences`, `prompts` (when `tenant_id` is not null) includes `WHERE tenant_id = $1`. Unscoped queries exist only for operator reports and must be explicitly reviewed. For `prompts`, operator-level rows (`tenant_id IS NULL`) are accessible to all tenants — this is by design.
2. **Idempotent publish detection.** Two concurrent `publish_events` inserts for the same `(tenant_id, source_name, source_post_id)` cannot both succeed. The loser's `UNIQUE` violation is expected and silently swallowed.
3. **Idempotent distribution.** Two concurrent `distribution_records` inserts for the same `(publish_event_id, platform)` cannot both succeed. The loser exits without calling the platform API.
4. **Status transitions.** `distribution_records.status` moves `pending → sent | failed | skipped`. It never moves backward. A `sent` row is terminal.
5. **Retry policy.** The share-sweep may re-attempt a `failed` distribution by upserting the row if the failure was transient (rate-limit, 5xx). Non-transient failures (auth, duplicate content, validation) are not auto-retried.
6. **Monotonic `last_seen_at`.** `source_state.last_seen_at` never moves backward.
7. **Secret isolation.** `tenant_secrets` rows for tenant A are never read in the context of tenant B. The tenant_id parameter is always bound before any secret lookup.
8. **Config consistency.** `tenant_config` and `cadences` rows are always created atomically with the `tenants` row. A `tenants` row without a matching `tenant_config` row is an error state.

## Retention

No automatic pruning in v1. These tables grow unboundedly. A future capability `astra prune --older-than 90d` is out of scope here.

## Migrations

- Schema versioning: a `schema_migrations` table records applied migration IDs.
- **Migration ownership**: every process that opens a DB connection (`astra run`, `astra ui`, CLI commands) runs the migration runner before doing anything else. Migrations are idempotent; re-running against an already-migrated DB is a safe no-op. This means whichever process starts first against a fresh DB will apply the schema — no separate `astra migrate` command is needed.
- Each migration is forward-only. No downgrade path.
- Adding a column or table: new migration appended.
- Renaming / dropping a column: new migration appended, with a note in this file explaining the semantic change.
