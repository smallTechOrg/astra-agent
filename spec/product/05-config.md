# Configuration

**Status:** DRAFT

## Overview

Astra uses a two-tier config model:

- **Operator-level** — settings and secrets that apply to the whole installation. Lives in `config/operator.yaml` and `config/.env` on the filesystem.
- **Tenant-level** — settings and secrets for each individual tenant. Lives entirely in the PostgreSQL database (`tenant_config`, `tenant_secrets`, `cadences` tables). Managed via the CLI or UI — no files to edit.

There are no per-tenant YAML or `.env` files. Everything about a tenant is in the DB.

## File layout

```
config/
├── operator.yaml      # Operator-wide settings (LLM provider, log level)
└── .env               # Operator-wide secrets (DATABASE_URL, LLM_API_KEY, ASTRA_UI_PASSWORD)
```

There are no per-tenant filesystem artifacts. All tenant config, secrets, and prompts are in the DB.

Prompts are stored in the `prompts` table (see [`07-data-model.md`](07-data-model.md#schema) and [`08-prompts.md`](08-prompts.md)). Operator defaults are seeded on first migration; tenant overrides are created via the UI.

## `operator.yaml`

```yaml
# config/operator.yaml

llm:
  provider: "groq"                # openai | anthropic | groq | gemini
  model: "llama-3.3-70b-versatile"
  temperature: 0.8
  max_tokens: 2048
  # api_key comes from env: LLM_API_KEY

log_level: "info"                 # debug | info | warning | error

daemon:
  share_sweep_cron: "*/10 * * * *"
  startup_grace_seconds: 5
```

## `config/.env`

Operator-level secrets. Gitignored. One flat file, plain `KEY=value`:

```
DATABASE_URL=postgresql://astra:astra@localhost:5432/astra
LLM_API_KEY=...
ASTRA_UI_PASSWORD=...        # Required if astra ui is bound to non-loopback
```

`DATABASE_URL` is the single point of DB configuration. All processes (`astra run`, `astra ui`, CLI commands) read it from here.

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

At daemon startup, for each enabled tenant:

1. **Config completeness**: `tenant_config` row exists. Missing row marks tenant degraded.
2. **Secret resolution**: all secrets required by enabled destinations are present and non-empty. Missing secrets for a disabled destination are OK.
3. **Cadence uniqueness**: enforced by DB `UNIQUE (tenant_id, name)` constraint. Violations at insert time, not at startup.
4. **Cron validity**: all `*_cron` values parse as valid 5-field cron expressions. Invalid cron marks the tenant degraded.
5. **Source type known**: `source_type` must match a registered source.

Failures for one tenant log a structured error and mark that tenant degraded. Other tenants load normally.

## Reload semantics

- The daemon reads tenant config from the DB at startup.
- Planned future capability: `astra reload` triggers re-read from DB without restart. Out of scope for v1.
- v1: restart `astra run` after any config change to pick it up.
- The UI shows a "Restart daemon to apply" banner after writes that require a restart.

## Deleted config surface

These keys existed in the old Astra and are **gone**:

- `config/tenants/<id>/tenant.yaml` — replaced by `tenant_config` table
- `config/tenants/<id>/.env` — replaced by `tenant_secrets` table
- `operator.yaml → database_path` — replaced by `DATABASE_URL` in `.env`
- `wordpress:` at root (was global, now per-tenant in DB)
- `twitter_bot.*` — engagement is out of scope
- `scheduler.post_cron`, `scheduler.engage_cron` — no longer exists
- `pollinations_api_key` — image generation removed
- `linkedin.access_token` at root — now per-tenant in `tenant_secrets`
