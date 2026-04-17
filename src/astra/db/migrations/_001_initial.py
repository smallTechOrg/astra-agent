"""Migration 001: initial schema.

Mirrors the DDL in spec/product/07-data-model.md#schema verbatim.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_state (
    tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name    TEXT NOT NULL,
    last_seen_at   TEXT,
    last_polled_at TEXT,
    needs_reauth   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, source_name)
);

CREATE TABLE IF NOT EXISTS destination_state (
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform      TEXT NOT NULL,
    needs_reauth  INTEGER NOT NULL DEFAULT 0,
    degraded      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    rate_limit_reset_at TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (tenant_id, platform)
);

CREATE TABLE IF NOT EXISTS publish_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    source_post_id  TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    excerpt         TEXT,
    published_at    TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    UNIQUE (tenant_id, source_name, source_post_id)
);

CREATE INDEX IF NOT EXISTS idx_publish_events_tenant_detected
    ON publish_events (tenant_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS distribution_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    publish_event_id  INTEGER NOT NULL REFERENCES publish_events(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    status            TEXT NOT NULL,
    platform_post_id  TEXT,
    copy              TEXT,
    error             TEXT,
    attempted_at      TEXT NOT NULL,
    completed_at      TEXT,
    UNIQUE (publish_event_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_distribution_records_tenant_status
    ON distribution_records (tenant_id, status);

CREATE TABLE IF NOT EXISTS scheduled_tweets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cadence_name      TEXT NOT NULL,
    text              TEXT,
    platform_post_id  TEXT,
    status            TEXT NOT NULL,
    error             TEXT,
    posted_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tweets_tenant_cadence_posted
    ON scheduled_tweets (tenant_id, cadence_name, posted_at DESC);
"""
