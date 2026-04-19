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

No other secrets belong in `.env`. `LLM_API_KEY` and all other operator-level secrets are stored in `operator_secrets` in the DB and managed via the UI.

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
| `sweep_cron` | `*/10 * * * *` | 5-field cron for retry sweeps |
| `startup_grace_seconds` | `5` | Seconds to wait before scheduler starts |
| `web_scraper_url` | `null` | URL of the external web-scraper service. If unset, the browser tool is unavailable and browser-only platforms will fail. |

Changing config via the UI takes effect on the next daemon restart (v1; hot-reload is a future capability).

## Operator secrets (in DB)

Operator-level secrets are stored in the `operator_secrets` table as key/value pairs.

Known keys:

| Key | Purpose |
|---|---|
| `LLM_API_KEY` | API key for the configured LLM provider |

The UI renders these as write-only `type=password` fields. The API returns presence only (`"set"` or `"empty"`), never values. See [`10-ui-dashboard.md`](10-ui-dashboard.md#secret-handling-rules).

The daemon reads `LLM_API_KEY` from `operator_secrets` at startup. If it is missing, the daemon logs a warning and continues — tenants that need LLM will be marked degraded.

> **Note:** Unlike the old architecture, there are no operator-level OAuth client IDs (`LINKEDIN_CLIENT_ID`, etc.). Platform credentials are always per-tenant, stored in `tenant_secrets`.

## Tenant configuration (in DB)

Tenant config is split across three tables:

| Concern | Table | Notes |
|---|---|---|
| Core settings (source, LLM overrides, approval mode) | `tenant_config` | One row per tenant |
| Enabled platforms | `tenant_platforms` | One row per platform per tenant |
| Cadences | `cadences` | One row per cadence job |

The UI and CLI are the write paths. The daemon reads from the DB at startup.

### `tenant_config` columns

| Column | Default | Notes |
|---|---|---|
| `source_type` | `wordpress` | Must match a registered source |
| `source_url` | `null` | Required for wordpress source |
| `source_username` | `null` | Required for wordpress source |
| `source_poll_cron` | `*/5 * * * *` | How often to poll for new content |
| `approval_mode` | `false` | When true, distribution plans require human approval |
| `llm_provider` | `null` | Per-tenant LLM override (falls back to operator) |
| `llm_model` | `null` | Per-tenant LLM override |
| `llm_temperature` | `null` | Per-tenant LLM override |
| `llm_max_tokens` | `null` | Per-tenant LLM override |

### `tenant_platforms` — dynamic destination registry

Platforms are **not** columns in `tenant_config`. They are rows in `tenant_platforms` — one per platform per tenant. This means:
- Adding a new platform to a tenant is an insert, not a schema migration.
- The set of available platforms is unbounded. Any platform the agent has knowledge for can be added.
- Each platform row has a JSONB `config` field for platform-specific settings (e.g. Mastodon instance URL, subreddit name, LinkedIn org ID).

Example rows for a tenant:

| tenant_id | platform | enabled | config |
|---|---|---|---|
| `acme-corp` | `bluesky` | `true` | `{"handle": "acme.bsky.social"}` |
| `acme-corp` | `mastodon` | `true` | `{"instance_url": "https://mastodon.social"}` |
| `acme-corp` | `devto` | `true` | `{}` |
| `acme-corp` | `linkedin` | `true` | `{"profile_type": "personal"}` |
| `acme-corp` | `twitter` | `false` | `{"via_browser": true}` |

## Tenant secrets (in DB)

Per-tenant secrets are stored in the `tenant_secrets` table as key/value pairs. Stored plaintext. Secret keys are platform-specific — they are not hardcoded in the schema.

Conventions for secret key naming:

| Pattern | Example | Purpose |
|---|---|---|
| `WP_APP_PASSWORD` | `WP_APP_PASSWORD` | WordPress application password (source) |
| `<PLATFORM>_*` | `BLUESKY_APP_PASSWORD` | Platform-specific credential |
| `<PLATFORM>_*` | `MASTODON_ACCESS_TOKEN` | Platform-specific credential |
| `<PLATFORM>_*` | `DEVTO_API_KEY` | Platform-specific credential |
| `<PLATFORM>_*` | `LINKEDIN_ACCESS_TOKEN` | Platform-specific credential |

The required secrets for a platform are determined by the platform knowledge store (`api_auth_type` field). The agent knows what credentials it needs by reading the knowledge entry. The UI can use this to show the correct input fields when adding a platform to a tenant.

The daemon reads secrets for a tenant by querying `tenant_secrets WHERE tenant_id = $1`. Secrets for tenant A are never read in the context of tenant B — see [`../engineering/tenant-isolation.md`](../engineering/tenant-isolation.md).

## Platform knowledge (in DB)

Platform knowledge entries are stored in the `platform_knowledge` table. See [`07-data-model.md`](07-data-model.md#schema) for the full schema and [`02-architecture.md`](02-architecture.md#platform-knowledge-store) for the design rationale.

- **Global defaults** (`tenant_id IS NULL`) are shipped as seed data on first migration. Astra seeds knowledge for: Bluesky, Mastodon, DEV.to, LinkedIn (personal profile).
- **Tenant overrides** (`tenant_id = <id>`) are created by the operator or the agent when platform-specific adjustments are needed (e.g. custom Mastodon instance URL).
- Knowledge is **operator-editable** via the UI. The agent can append lessons but cannot modify operator-written knowledge.

## Config validation

At daemon startup:

1. **Operator config**: `operator_config` row must exist. If missing (fresh DB), the migration seeds defaults.
2. **Operator secrets**: `LLM_API_KEY` must be present and non-empty. Missing key logs a warning; tenants needing LLM are marked degraded.
3. **Web-scraper**: if `web_scraper_url` is set, daemon pings it. If unreachable, logs a warning — browser-dependent platforms will fail at execution time, not at startup.

For each enabled tenant:

1. **Config completeness**: `tenant_config` row exists. Missing row marks tenant degraded.
2. **Platform credentials**: for each enabled `tenant_platforms` row, the agent checks that the required secrets (per platform knowledge `api_auth_type`) are present in `tenant_secrets`. Missing secrets mark that platform degraded for this tenant, but do not block other platforms.
3. **Cadence validity**: enforced by DB `UNIQUE (tenant_id, name)` constraint. Each cadence's `platform` must have a corresponding enabled `tenant_platforms` row.
4. **Cron validity**: all `*_cron` values parse as valid 5-field cron expressions. Invalid cron marks the tenant degraded.
5. **Source type known**: `source_type` must match a registered source.
6. **Platform knowledge exists**: for each enabled platform, global or tenant-scoped knowledge must exist. Missing knowledge logs a warning — the agent will attempt to proceed but may fail.

Failures for one tenant log a structured error and mark that tenant degraded. Other tenants load normally.

## Reload semantics

- The daemon reads all config (operator + tenant) from the DB at startup.
- Planned future capability: `astra reload` triggers re-read from DB without restart. Out of scope for v1.
- v1: restart `astra run` after any config change to pick it up.
- The UI shows a "Restart daemon to apply" banner after writes that require a restart.

## Deleted config surface

These keys existed in the old Astra and are **gone**:

- `config/operator.yaml` — replaced by `operator_config` table
- `config/tenants/<id>/tenant.yaml` — replaced by `tenant_config` + `tenant_platforms` tables
- `config/tenants/<id>/.env` — replaced by `tenant_secrets` table
- `config/.env → LLM_API_KEY` — replaced by `operator_secrets` table
- `operator.yaml → database_path` — replaced by `DATABASE_URL` in `.env`
- `tenant_config.linkedin_enabled/twitter_enabled` — replaced by `tenant_platforms` rows
- `LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET` as operator secrets — OAuth credentials are now per-tenant
- `twitter_bot.*` — engagement is out of scope
- `scheduler.post_cron`, `scheduler.engage_cron` — no longer exists
- `pollinations_api_key` — image generation removed
