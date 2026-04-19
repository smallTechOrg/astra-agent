# Tenancy

**Status:** DRAFT

## What a tenant is

A **tenant** is the unit of multi-tenancy in Astra. One tenant represents one brand/customer/account and owns:

- a unique **tenant ID** (slug, lowercase-kebab-case, immutable) — e.g. `acme-corp`
- a display **name** — human-readable string for logs and CLI output
- exactly one **source** (today: a WordPress site; extensible per [`09-extensibility.md`](09-extensibility.md))
- zero or more **destinations** — each an enabled platform (Bluesky, Mastodon, DEV.to, LinkedIn, etc.) with its own credentials and config, stored in `tenant_destinations`
- zero or more **cadence configurations** (independently scheduled posting jobs for any platform)
- an **approval mode** flag — when true, distribution plans require human approval before execution
- its own **state** in the database (all rows scoped by `tenant_id`)
- its own **secrets** (all stored in the `tenant_secrets` DB table, scoped by `tenant_id`)
- its own **prompt overrides** (optional, in `prompts` DB table with `tenant_id`)

A tenant can be `enabled: true` or `enabled: false`. Disabled tenants are loaded into memory but no jobs run for them.

## Tenant lifecycle

### Create
- `astra tenant add <id> --name "Display Name"` inserts a `tenants` row and an empty `tenant_config` row. Or use the UI onboarding wizard.
- The tenant starts `enabled: false` until the operator fills in credentials and enables it.

### Configure
- Operator fills in source URL, destination platforms with their credentials, and cadences via the UI wizard or via CLI commands.
- For each destination platform, operator provides the required credentials (API keys, OAuth tokens, or browser session). See [`05-config.md`](05-config.md) for per-platform credential requirements.
- Secrets are written to `tenant_secrets`; config to `tenant_config`, `tenant_destinations`, and `cadences`.

### Enable
- Set `tenants.enabled = true` via `astra tenant enable <id>` or the UI toggle.
- Next daemon restart picks up the tenant and starts its polling + cadence jobs.

### Disable
- `tenants.enabled = false` stops all scheduled jobs for this tenant on next daemon restart.
- Existing state (publish events, distribution records) is preserved.
- Re-enabling resumes from where it left off; posts published during the disabled window are not backfilled unless the operator manually triggers `astra distribute`.

### Remove
- `astra tenant remove <id>` or the UI delete action cascades-deletes all DB rows scoped to that `tenant_id`. This is destructive and requires a confirmation prompt.

## Isolation guarantees

These are the contractual properties tenants observe. The engineering patterns Astra uses to maintain them live in [`../engineering/tenant-isolation.md`](../engineering/tenant-isolation.md); any code that breaks one of these guarantees is a bug.

1. **Data isolation.** Every row in every non-`tenants` table has a `tenant_id` column. No query reads rows across tenants except operator-level reports.
2. **Error isolation.** An exception raised while processing tenant A never prevents tenant B's scheduled jobs from running.
3. **Rate-limit isolation.** A 429 from Twitter for tenant A does not cause Astra to back off calls for tenant B. Rate-limit state is tenant-scoped.
4. **Credential isolation.** Tenant A's credentials are never used for tenant B's API calls.
5. **Secret isolation.** `tenant_secrets` rows for tenant A are never read in the context of tenant B. Every secret lookup is parameterized by `tenant_id`.

## Secrets

### Where secrets live
- **Tenant secrets** in the `tenant_secrets` DB table, keyed by `(tenant_id, key)`.
- **Operator secrets** (`LLM_API_KEY`, shared OAuth client credentials) in the `operator_secrets` DB table.
- **Bootstrap secrets** (`DATABASE_URL`, `ASTRA_UI_PASSWORD`) in `config/.env` (needed before DB is available).
- **Never** in source code, git history, logs, or commit messages.

### Which values are secrets
- WordPress application password (`WP_APP_PASSWORD`)
- Bluesky app password (`BLUESKY_APP_PASSWORD`)
- Mastodon access token (`MASTODON_ACCESS_TOKEN`)
- DEV.to API key (`DEVTO_API_KEY`)
- LinkedIn access token (`LINKEDIN_ACCESS_TOKEN`)
- Any platform-specific API keys or tokens added in the future
- Browser session cookies (managed by `web-scraper`, not stored in Astra DB)

### Operator-level keys
- `LLM_API_KEY` — shared by default. Per-tenant override: set `llm_provider`/`llm_model` in `tenant_config` and store the key in `tenant_secrets` under a distinct key name.
- `DATABASE_URL` — PostgreSQL connection string. Operator-level only.

## Failure isolation in practice

The daemon startup sequence:

1. Load all tenants.
2. For each tenant, attempt to construct its clients. If any required credential is missing or malformed:
   - Log a structured error `tenant_startup_failed` with `tenant_id` and the specific reason.
   - Mark the tenant as "degraded" for this process lifetime.
   - Continue loading other tenants.
3. Degraded tenants skip their scheduled jobs (they'd fail anyway) but remain visible in `astra tenant list` and `astra health`.
4. Operator fixes credentials → `astra reload` or restart → tenant re-enters normal operation.

A single tenant's misconfiguration never prevents the daemon from starting or other tenants from running.

## Token expiry

LinkedIn tokens expire (~60 days for member tokens). Astra does not attempt automatic refresh:

- On any LinkedIn API `401`, mark tenant `linkedin.needs_reauth = true` in `source_state` (or equivalent).
- Subsequent LinkedIn distribution attempts for that tenant are skipped with reason `needs_reauth` until the operator runs `astra auth linkedin --tenant <id>` (CLI) or re-authenticates via the UI, which updates `tenant_secrets.LINKEDIN_ACCESS_TOKEN`.
- `astra health` and `astra tenant list` both surface this state.

## Naming

- Tenant IDs are slugs: `[a-z0-9][a-z0-9-]*[a-z0-9]`, 2–40 chars. Validated at tenant creation.
- Tenant names are free-form UTF-8 for display only.
- Tenant IDs are **immutable** once created. To rename, remove and re-create.
