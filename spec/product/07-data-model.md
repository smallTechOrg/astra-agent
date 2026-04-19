# Data model

**Status:** DRAFT

PostgreSQL, via `asyncpg`. Connection configured via `DATABASE_URL` in the operator `.env` (e.g. `postgresql://astra:astra@localhost:5432/astra`). One database, all tenants. Every non-`tenants` table has a `tenant_id` column and is always queried with `WHERE tenant_id = $1`.

All timestamps are `TIMESTAMPTZ` in UTC. Native PostgreSQL datetime type; comparisons and ordering are correct by default.

## Schema

```sql
-- ── Operator configuration ──────────────────────────────────
-- Singleton row. Written by UI/CLI; read by daemon.
-- Seeded with defaults on first migration.

CREATE TABLE operator_config (
    id                      INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    llm_provider            TEXT NOT NULL DEFAULT 'groq',
    llm_model               TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
    llm_temperature         REAL NOT NULL DEFAULT 0.8,
    llm_max_tokens          INTEGER NOT NULL DEFAULT 2048,
    log_level               TEXT NOT NULL DEFAULT 'info',
    sweep_cron              TEXT NOT NULL DEFAULT '*/10 * * * *',
    startup_grace_seconds   INTEGER NOT NULL DEFAULT 5,
    web_scraper_url         TEXT,                 -- URL of the external web-scraper service (nullable, browser tool disabled if unset)
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Operator secrets ────────────────────────────────────────
-- Operator-level secrets. Values stored plaintext.
-- Known keys: LLM_API_KEY

CREATE TABLE operator_secrets (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenants ──────────────────────────────────────────────────

CREATE TABLE tenants (
    id           TEXT PRIMARY KEY,              -- slug, set at creation
    name         TEXT NOT NULL,                 -- display name
    enabled      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant configuration ─────────────────────────────────────
-- Core tenant settings. Platform-specific config lives in tenant_platforms.

CREATE TABLE tenant_config (
    tenant_id               TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    -- Source
    source_type             TEXT NOT NULL DEFAULT 'wordpress',
    source_url              TEXT,
    source_username         TEXT,
    source_poll_cron        TEXT NOT NULL DEFAULT '*/5 * * * *',
    -- Approval mode
    approval_mode           BOOLEAN NOT NULL DEFAULT false,
    -- Optional per-tenant LLM override
    llm_provider            TEXT,
    llm_model               TEXT,
    llm_temperature         REAL,
    llm_max_tokens          INTEGER,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant secrets ───────────────────────────────────────────
-- Per-tenant secrets. Values stored plaintext.
-- Keys are platform-specific (e.g. WP_APP_PASSWORD, BLUESKY_APP_PASSWORD,
-- MASTODON_ACCESS_TOKEN, DEVTO_API_KEY, LINKEDIN_ACCESS_TOKEN, etc.)

CREATE TABLE tenant_secrets (
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

-- ── Tenant platforms ─────────────────────────────────────────
-- Which platforms a tenant distributes to. One row per platform per tenant.
-- The platform name is a free-text identifier (e.g. "bluesky", "mastodon",
-- "devto", "linkedin", "twitter", "reddit", "facebook").
-- No hardcoded enum — any platform the agent has knowledge about can be added.

CREATE TABLE tenant_platforms (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,                  -- free-text platform identifier
    enabled     BOOLEAN NOT NULL DEFAULT true,
    config      JSONB NOT NULL DEFAULT '{}',   -- platform-specific config (e.g. mastodon instance URL, subreddit name)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, platform)
);

-- ── Platform knowledge store ─────────────────────────────────
-- Runtime-learned knowledge about how to interact with each platform.
-- Rows with tenant_id IS NULL are global defaults (shipped as seed data).
-- Rows with a tenant_id are tenant-specific overrides.
-- Resolution: tenant row → global row.

CREATE TABLE platform_knowledge (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT REFERENCES tenants(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    access_method   TEXT NOT NULL DEFAULT 'browser',  -- 'api' | 'browser' | 'both'
    -- API knowledge (nullable — not all platforms have APIs)
    api_base_url    TEXT,
    api_auth_type   TEXT,                      -- 'bearer_token' | 'api_key' | 'oauth2' | 'app_password'
    api_endpoints   JSONB,                     -- { "post": { "method": "POST", "path": "/...", "body_template": {...} }, ... }
    -- Browser knowledge (nullable — fallback to browser if API unavailable)
    browser_compose_url TEXT,
    browser_hints       JSONB,                 -- hints for the agent: { "text_field": "main textarea", "submit_button": "Post", ... }
    -- Content constraints
    content_constraints JSONB NOT NULL DEFAULT '{}',  -- { "max_text_length": 300, "supports_images": true, ... }
    -- Lessons learned by the agent (append-only by agent, editable by operator)
    lessons         JSONB NOT NULL DEFAULT '[]',       -- ["Rate limit: 1666/day", "Images must be uploaded as blobs first", ...]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, platform)
);

-- Partial unique index for global defaults (tenant_id IS NULL).
CREATE UNIQUE INDEX idx_platform_knowledge_global_default
    ON platform_knowledge (platform) WHERE tenant_id IS NULL;

-- ── Cadences ─────────────────────────────────────────────────
-- Independently scheduled posting jobs. One row per cadence.

CREATE TABLE cadences (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    platform        TEXT NOT NULL,              -- which platform this cadence posts to
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

-- ── Publish events ───────────────────────────────────────────
-- Content detected from sources. Generic: supports blogs, media, etc.

CREATE TABLE publish_events (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name       TEXT NOT NULL,
    source_content_id TEXT NOT NULL,             -- unique ID from the source (e.g. WP post ID)
    content_type      TEXT NOT NULL,             -- 'blog' | 'media' | future types
    title             TEXT,                      -- nullable: media may not have a title
    url               TEXT,                      -- nullable: media may not have a URL
    body              TEXT,                      -- full body / description
    excerpt           TEXT,
    images            JSONB NOT NULL DEFAULT '[]',  -- [{"url": "...", "alt": "..."}]
    metadata          JSONB NOT NULL DEFAULT '{}',  -- source-specific extra data
    published_at      TIMESTAMPTZ NOT NULL,
    detected_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, source_name, source_content_id)
);

CREATE INDEX idx_publish_events_tenant_detected
    ON publish_events (tenant_id, detected_at DESC);

-- ── Distribution plans ───────────────────────────────────────
-- One plan per publish event. Contains the agent's overall decision.

CREATE TABLE distribution_plans (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    publish_event_id  BIGINT NOT NULL REFERENCES publish_events(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'planning',
                      -- 'planning' | 'pending_approval' | 'executing' | 'completed' | 'partial' | 'failed' | 'rejected'
    rejection_reason  TEXT,                      -- set when status = 'rejected'
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (publish_event_id)                   -- one plan per event
);

CREATE INDEX idx_distribution_plans_tenant_status
    ON distribution_plans (tenant_id, status);

-- ── Plan items ───────────────────────────────────────────────
-- One row per platform per distribution plan.

CREATE TABLE plan_items (
    id                BIGSERIAL PRIMARY KEY,
    plan_id           BIGINT NOT NULL REFERENCES distribution_plans(id) ON DELETE CASCADE,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
                      -- 'pending' | 'approved' | 'executing' | 'sent' | 'failed' | 'skipped'
    copy              TEXT,                      -- generated platform-specific copy
    media_refs        JSONB NOT NULL DEFAULT '[]',  -- media to attach
    reasoning         TEXT,                      -- agent's reasoning for this platform selection + copy
    skip_reason       TEXT,                      -- set when status = 'skipped'
    platform_post_id  TEXT,                      -- set on successful post
    platform_post_url TEXT,                      -- URL to the published post
    error             TEXT,                      -- set on failure
    tool_used         TEXT,                      -- 'http' | 'browser' — which tool executed this
    executed_at       TIMESTAMPTZ,
    UNIQUE (plan_id, platform)
);

CREATE INDEX idx_plan_items_plan
    ON plan_items (plan_id);

-- ── Action traces ────────────────────────────────────────────
-- Every action the agent takes is recorded here. Immutable, append-only.
-- This is the core traceability/debuggability table.

CREATE TABLE action_traces (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        UUID NOT NULL DEFAULT gen_random_uuid(),
    plan_id         BIGINT REFERENCES distribution_plans(id) ON DELETE CASCADE,
    plan_item_id    BIGINT REFERENCES plan_items(id) ON DELETE CASCADE,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sequence        INTEGER NOT NULL,            -- ordering within a plan/plan_item
    action_type     TEXT NOT NULL,
                    -- 'llm_call' | 'http_request' | 'http_response' |
                    -- 'browser_navigate' | 'browser_fill' | 'browser_click' |
                    -- 'browser_upload' | 'browser_read' |
                    -- 'knowledge_read' | 'knowledge_write' |
                    -- 'decision' | 'error' | 'skip'
    summary         TEXT NOT NULL,               -- human-readable one-liner
    input           JSONB,                       -- what went into the action (redacted secrets)
    output          JSONB,                       -- what came back (truncated if large)
    duration_ms     INTEGER,
    parent_trace_id UUID,                        -- for nesting (e.g. browser actions under "post to platform")
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_action_traces_plan
    ON action_traces (plan_id, sequence);
CREATE INDEX idx_action_traces_plan_item
    ON action_traces (plan_item_id, sequence);
CREATE INDEX idx_action_traces_tenant_created
    ON action_traces (tenant_id, created_at DESC);

-- ── Cadence posts ────────────────────────────────────────────
-- Records of cadence-generated posts (replaces scheduled_tweets).
-- Platform-agnostic — cadences can post to any platform.

CREATE TABLE cadence_posts (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cadence_name     TEXT NOT NULL,
    platform         TEXT NOT NULL,
    text             TEXT,
    platform_post_id TEXT,
    platform_post_url TEXT,
    status           TEXT NOT NULL,              -- 'sent' | 'failed' | 'skipped'
    error            TEXT,
    posted_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_cadence_posts_tenant_cadence_posted
    ON cadence_posts (tenant_id, cadence_name, posted_at DESC);

-- ── Daemon heartbeat ────────────────────────────────────────
-- Singleton row written by `astra run` on startup. Read by `astra ui`.

CREATE TABLE daemon_heartbeat (
    id           INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    started_at   TIMESTAMPTZ NOT NULL,
    version      TEXT NOT NULL,
    tenant_count INTEGER NOT NULL DEFAULT 0,
    job_count    INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Invariants

These must hold at all times. Any code that violates them is a bug.

1. **Tenant scoping.** Every query against tenant-scoped tables includes `WHERE tenant_id = $1`. Unscoped queries exist only for operator reports and must be explicitly reviewed. For `prompts` and `platform_knowledge`, global rows (`tenant_id IS NULL`) are accessible to all tenants — this is by design.
2. **Operator singletons.** `operator_config` always has exactly one row with `id = 1`. The migration seeds it; it is never deleted. `operator_secrets` has at most one row per key.
3. **Idempotent publish detection.** Two concurrent `publish_events` inserts for the same `(tenant_id, source_name, source_content_id)` cannot both succeed. The loser's `UNIQUE` violation is expected and silently swallowed.
4. **One plan per event.** The `UNIQUE (publish_event_id)` constraint on `distribution_plans` ensures a content event is never planned twice. If re-distribution is needed, the operator uses the manual distribute command which creates a new publish event.
5. **One item per platform per plan.** `UNIQUE (plan_id, platform)` on `plan_items`. No double-posting.
6. **Status transitions.** `plan_items.status` moves `pending → approved → executing → sent | failed | skipped`. It never moves backward. A `sent` row is terminal.
7. **Traces are immutable.** `action_traces` is append-only. Rows are never updated or deleted (except by retention pruning, future).
8. **Monotonic `last_seen_at`.** `source_state.last_seen_at` never moves backward.
9. **Secret isolation.** `tenant_secrets` rows for tenant A are never read in the context of tenant B. The tenant_id parameter is always bound before any secret lookup.
10. **Config consistency.** `tenant_config` row is always created atomically with the `tenants` row. A `tenants` row without a matching `tenant_config` row is an error state.
11. **Knowledge resolution.** Platform knowledge lookups always check tenant-scoped override first, then global default. The agent never bypasses this resolution order.
12. **Trace completeness.** Every tool invocation (LLM, HTTP, browser) produces at least one `action_traces` row. Silent actions are bugs.

## Retention

No automatic pruning in v1. These tables grow unboundedly. A future capability `astra prune --older-than 90d` is out of scope here.

## Migrations

- Schema versioning: a `schema_migrations` table records applied migration IDs.
- **Migration ownership**: every process that opens a DB connection (`astra run`, `astra ui`, CLI commands) runs the migration runner before doing anything else. Migrations are idempotent; re-running against an already-migrated DB is a safe no-op. This means whichever process starts first against a fresh DB will apply the schema — no separate `astra migrate` command is needed.
- Each migration is forward-only. No downgrade path.
- Adding a column or table: new migration appended.
- Renaming / dropping a column: new migration appended, with a note in this file explaining the semantic change.
