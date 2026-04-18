"""Migration 001: initial schema.

Mirrors the DDL in spec/product/07-data-model.md#schema verbatim.
All ten tables created in one shot so the DB matches spec end-state.
"""

from __future__ import annotations

SQL = """
-- ── Tenants ──────────────────────────────────────────────────────

CREATE TABLE tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    enabled      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant configuration ─────────────────────────────────────────

CREATE TABLE tenant_config (
    tenant_id                   TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    source_type                 TEXT NOT NULL DEFAULT 'wordpress',
    source_url                  TEXT,
    source_username             TEXT,
    source_poll_cron            TEXT NOT NULL DEFAULT '*/5 * * * *',
    linkedin_enabled            BOOLEAN NOT NULL DEFAULT false,
    linkedin_org_id             TEXT,
    linkedin_prompt             TEXT NOT NULL DEFAULT 'linkedin_announcement',
    twitter_enabled             BOOLEAN NOT NULL DEFAULT false,
    twitter_announcement_prompt TEXT NOT NULL DEFAULT 'twitter_announcement',
    llm_provider                TEXT,
    llm_model                   TEXT,
    llm_temperature             REAL,
    llm_max_tokens              INTEGER,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tenant secrets ───────────────────────────────────────────────

CREATE TABLE tenant_secrets (
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

-- ── Cadences ─────────────────────────────────────────────────────

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

-- ── Source state ─────────────────────────────────────────────────

CREATE TABLE source_state (
    tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name    TEXT NOT NULL,
    last_seen_at   TIMESTAMPTZ,
    last_polled_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, source_name)
);

-- ── Destination state ────────────────────────────────────────────

CREATE TABLE destination_state (
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform     TEXT NOT NULL,
    needs_reauth BOOLEAN NOT NULL DEFAULT false,
    degraded     BOOLEAN NOT NULL DEFAULT false,
    last_error   TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, platform)
);

-- ── Publish events ───────────────────────────────────────────────

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

-- ── Distribution records ─────────────────────────────────────────

CREATE TABLE distribution_records (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    publish_event_id  BIGINT NOT NULL REFERENCES publish_events(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    status            TEXT NOT NULL,
    platform_post_id  TEXT,
    copy              TEXT,
    error             TEXT,
    attempted_at      TIMESTAMPTZ NOT NULL,
    completed_at      TIMESTAMPTZ,
    UNIQUE (publish_event_id, platform)
);

CREATE INDEX idx_distribution_records_tenant_status
    ON distribution_records (tenant_id, status);

-- ── Daemon heartbeat ─────────────────────────────────────────────

CREATE TABLE daemon_heartbeat (
    id           INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    started_at   TIMESTAMPTZ NOT NULL,
    version      TEXT NOT NULL,
    tenant_count INTEGER NOT NULL DEFAULT 0,
    job_count    INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Scheduled (cadence) tweets ───────────────────────────────────

CREATE TABLE scheduled_tweets (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cadence_name     TEXT NOT NULL,
    text             TEXT,
    platform_post_id TEXT,
    status           TEXT NOT NULL,
    error            TEXT,
    posted_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_scheduled_tweets_tenant_cadence_posted
    ON scheduled_tweets (tenant_id, cadence_name, posted_at DESC);

-- ── Prompts ──────────────────────────────────────────────────────
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

CREATE UNIQUE INDEX idx_prompts_operator_default
    ON prompts (name) WHERE tenant_id IS NULL;
"""
