"""Migration 003: operator_config + operator_secrets tables.

Per spec/product/05-config.md: operator.yaml eliminated. All operator config
(LLM, daemon cron, log level) now lives in the operator_config DB table.
Operator secrets (LLM_API_KEY, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET)
live in operator_secrets.
"""

from __future__ import annotations

SQL = """
-- ── Operator configuration (singleton) ──────────────────────
-- Replaces operator.yaml. Written by UI/CLI; read by daemon.
-- Seeded with defaults.

CREATE TABLE IF NOT EXISTS operator_config (
    id                      INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    llm_provider            TEXT NOT NULL DEFAULT 'groq',
    llm_model               TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
    llm_temperature         REAL NOT NULL DEFAULT 0.8,
    llm_max_tokens          INTEGER NOT NULL DEFAULT 2048,
    log_level               TEXT NOT NULL DEFAULT 'info',
    share_sweep_cron        TEXT NOT NULL DEFAULT '*/10 * * * *',
    startup_grace_seconds   INTEGER NOT NULL DEFAULT 5,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the singleton row with defaults. Idempotent.
INSERT INTO operator_config (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- ── Operator secrets ────────────────────────────────────────
-- Operator-level secrets. Values stored plaintext.
-- Known keys: LLM_API_KEY, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET

CREATE TABLE IF NOT EXISTS operator_secrets (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
