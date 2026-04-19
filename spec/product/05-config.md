# Configuration

**Status:** DRAFT

## Overview

Astra uses a two-tier config model. **Everything lives in the PostgreSQL database** except two bootstrap secrets that must exist before a DB connection can be established.

- **Operator-level** — settings and secrets that apply to the whole installation. Stored in `operator_config` and `operator_secrets` tables in the database. Managed via the UI or CLI — no YAML files.
- **Tenant-level** — settings and secrets for each individual tenant. Stored in `tenant_config`, `tenant_secrets`, `cadences` tables. Managed via the UI or CLI — no files to edit.

There are no per-tenant filesystem artifacts. There is no `operator.yaml`. The only file on disk is `config/.env` with bootstrap secrets.

## File layout

```
config/
└── .env               # Bootstrap secrets only (DATABASE_URL, ASTRA_UI_PASSWORD)
```

All config, secrets, and prompts are in the DB. Prompts are stored in the `prompts` table (see [`07-data-model.md`](07-data-model.md#schema) and [`08-prompts.md`](08-prompts.md)). Operator defaults are seeded on first migration; tenant overrides are created via the UI.

## `config/.env` (bootstrap only)

Two secrets that cannot live in the DB because they are needed before a DB connection exists. Gitignored. One flat file, plain `KEY=value`:

```
DATABASE_URL=postgresql://astra:astra@localhost:5432/astra
ASTRA_UI_PASSWORD=...        # Required if astra ui is bound to non-loopback
```

`DATABASE_URL` is the single point of DB configuration. All processes (`astra run`, `astra ui`, CLI commands) read it from here.

`ASTRA_UI_PASSWORD` is the operator-level password for the web UI session cookie. It must be available before the DB is connected because the session middleware is configured at app startup. On loopback, if unset, the UI starts in no-auth dev mode.

No other secrets belong in `.env`. `LLM_API_KEY`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and all other operator-level secrets are stored in `operator_secrets` in the DB and managed via the UI.

## Operator configuration (in DB)

Operator config is a singleton row in the `operator_config` table (see [`07-data-model.md`](07-data-model.md#schema)). The UI and CLI are the write paths. The daemon reads from the DB at startup.

On first migration, Astra seeds the `operator_config` row with defaults:

| Setting | Default | Notes |
|---|---|---|
| `llm_provider` | `groq` | `openai` \| `anthropic` \| `groq` \| `gemini` |
| `llm_model` | `llama-3.3-70b-versatile` | Provider-specific model name |
| `llm_temperature` | `0.8` | |
| `llm_max_tokens` | `2048` | |
| `log_level` | `info` | `debug` \| `info` \| `warning` \| `error` |
| `share_sweep_cron` | `*/10 * * * *` | 5-field cron for retry sweeps |
| `startup_grace_seconds` | `5` | Seconds to wait before scheduler starts |

These values replace what was previously in `operator.yaml`. Changing them via the UI takes effect on the next daemon restart (v1; hot-reload is a future capability).

## Operator secrets (in DB)

Operator-level secrets are stored in the `operator_secrets` table as key/value pairs.

Known keys:

| Key | Purpose |
|---|---|
| `LLM_API_KEY` | API key for the configured LLM provider |
| `LINKEDIN_CLIENT_ID` | LinkedIn OAuth2 client ID (operator-level, shared across tenants) |
| `LINKEDIN_CLIENT_SECRET` | LinkedIn OAuth2 client secret |

The UI renders these as write-only `type=password` fields. The API returns presence only (`"set"` or `"empty"`), never values. See [`10-ui-dashboard.md`](10-ui-dashboard.md#secret-handling-rules).

The daemon reads `LLM_API_KEY` from `operator_secrets` at startup. If it is missing, the daemon logs a warning and continues — tenants that need LLM will be marked degraded.

## Tenant configuration (in DB)

Tenant config is stored in `tenant_config` and `cadences` tables. The UI and CLI are the write paths. The daemon reads from the DB at startup (and on future hot-reload when `astra reload` lands).

Equivalent to the old `tenant.yaml`:

| Old YAML key | DB table / column |
|---|---|
| `id` | `tenants.id` |
| `name` | `tenants.name` |
| `enabled` | `tenants.enabled` |
| `source.type` | `tenant_config.source_type` |
| `source.url` | `tenant_config.source_url` |
| `source.username` | `tenant_config.source_username` |
| `source.poll_cron` | `tenant_config.source_poll_cron` |
| `destinations.linkedin.enabled` | `tenant_config.linkedin_enabled` |
| `destinations.linkedin.organization_id` | `tenant_config.linkedin_org_id` |
| `destinations.linkedin.prompt` | `tenant_config.linkedin_prompt` |
| `destinations.twitter.enabled` | `tenant_config.twitter_enabled` |
| `destinations.twitter.announcement_prompt` | `tenant_config.twitter_announcement_prompt` |
| `cadences[]` | `cadences` table (one row per cadence) |
| `llm.*` overrides | `tenant_config.llm_*` columns |

## Tenant secrets (in DB)

Per-tenant secrets are stored in the `tenant_secrets` table as key/value pairs. Stored plaintext.

Known keys:

| Key | Purpose |
|---|---|
| `WP_APP_PASSWORD` | WordPress application password |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth2 access token |
| `TWITTER_API_KEY` | Twitter API key |
| `TWITTER_API_SECRET` | Twitter API secret |
| `TWITTER_ACCESS_TOKEN` | Twitter access token |
| `TWITTER_ACCESS_SECRET` | Twitter access token secret |

The daemon reads secrets for a tenant by querying `tenant_secrets WHERE tenant_id = $1`. Secrets for tenant A are never read in the context of tenant B — see [`../engineering/tenant-isolation.md`](../engineering/tenant-isolation.md).

## Config validation

At daemon startup:

1. **Operator config**: `operator_config` row must exist. If missing (fresh DB), the migration seeds defaults.
2. **Operator secrets**: `LLM_API_KEY` must be present and non-empty. Missing key logs a warning; tenants needing LLM are marked degraded.

For each enabled tenant:

1. **Config completeness**: `tenant_config` row exists. Missing row marks tenant degraded.
2. **Secret resolution**: all secrets required by enabled destinations are present and non-empty. Missing secrets for a disabled destination are OK.
3. **Cadence uniqueness**: enforced by DB `UNIQUE (tenant_id, name)` constraint. Violations at insert time, not at startup.
4. **Cron validity**: all `*_cron` values parse as valid 5-field cron expressions. Invalid cron marks the tenant degraded.
5. **Source type known**: `source_type` must match a registered source.

Failures for one tenant log a structured error and mark that tenant degraded. Other tenants load normally.

## Reload semantics

- The daemon reads all config (operator + tenant) from the DB at startup.
- Planned future capability: `astra reload` triggers re-read from DB without restart. Out of scope for v1.
- v1: restart `astra run` after any config change to pick it up.
- The UI shows a "Restart daemon to apply" banner after writes that require a restart.

## Deleted config surface

These keys existed in the old Astra and are **gone**:

- `config/operator.yaml` — replaced by `operator_config` table
- `config/tenants/<id>/tenant.yaml` — replaced by `tenant_config` table
- `config/tenants/<id>/.env` — replaced by `tenant_secrets` table
- `config/.env → LLM_API_KEY` — replaced by `operator_secrets` table
- `operator.yaml → database_path` — replaced by `DATABASE_URL` in `.env`
- `wordpress:` at root (was global, now per-tenant in DB)
- `twitter_bot.*` — engagement is out of scope
- `scheduler.post_cron`, `scheduler.engage_cron` — no longer exists
- `pollinations_api_key` — image generation removed
- `linkedin.access_token` at root — now per-tenant in `tenant_secrets`
