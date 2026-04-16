# Tenancy

**Status:** DRAFT

## What a tenant is

A **tenant** is the unit of multi-tenancy in Astra. One tenant represents one brand/customer/account and owns:

- a unique **tenant ID** (slug, lowercase-kebab-case, immutable) — e.g. `acme-corp`
- a display **name** — human-readable string for logs and CLI output
- exactly one **source** (today: a WordPress site)
- zero or one **LinkedIn destination** (an organization page)
- zero or one **Twitter destination** (an X/Twitter account)
- zero or more **cadence configurations** (independently scheduled Twitter posting jobs)
- its own **state** in the database (all rows scoped by `tenant_id`)
- its own **secrets** (all stored in `config/tenants/<id>/.env`, gitignored)
- its own **prompt overrides** (optional, in `config/tenants/<id>/prompts/`)

A tenant can be `enabled: true` or `enabled: false`. Disabled tenants are loaded into memory but no jobs run for them.

## Tenant lifecycle

### Create
- `astra tenant add <id> --name "Display Name"` creates `config/tenants/<id>/tenant.yaml` with a commented template and an empty `.env`.
- The tenant starts `enabled: false` until the operator fills in credentials and enables it.

### Configure
- Operator edits `config/tenants/<id>/tenant.yaml` to point at the WordPress URL, LinkedIn org ID, Twitter API keys, and defines cadences.
- Operator fills secrets in `config/tenants/<id>/.env`.
- Operator runs `astra auth linkedin --tenant <id>` if a fresh LinkedIn token is needed.

### Enable
- Set `enabled: true` in `tenant.yaml`.
- Next daemon reload picks up the tenant and starts its polling + cadence jobs.
- `astra tenant enable <id>` / `disable <id>` are equivalent CLI shortcuts.

### Disable
- `enabled: false` stops all scheduled jobs for this tenant.
- Existing state (publish events, distribution records) is preserved.
- Re-enabling resumes from where it left off; posts published during the disabled window are not backfilled unless the operator manually triggers `astra distribute`.

### Remove
- `astra tenant remove <id>` deletes the YAML and `.env` files and deletes all DB rows scoped to that `tenant_id`. This is destructive and requires a confirmation prompt.

## Isolation guarantees

These are the contractual properties tenants observe. The engineering patterns Astra uses to maintain them live in [`../engineering/tenant-isolation.md`](../engineering/tenant-isolation.md); any code that breaks one of these guarantees is a bug.

1. **Data isolation.** Every row in every non-`tenants` table has a `tenant_id` column. No query reads rows across tenants except operator-level reports.
2. **Error isolation.** An exception raised while processing tenant A never prevents tenant B's scheduled jobs from running.
3. **Rate-limit isolation.** A 429 from Twitter for tenant A does not cause Astra to back off calls for tenant B. Rate-limit state is tenant-scoped.
4. **Credential isolation.** Tenant A's credentials are never used for tenant B's API calls.
5. **Secret isolation.** A tenant's `.env` is only read by that tenant's runner. Env vars are not globally shared into the process except for operator-level keys.

## Secrets

### Where secrets live
- **Never** in `tenant.yaml` (YAML is considered operator-readable and could be checked in).
- **Always** in `config/tenants/<id>/.env`, which is gitignored.
- Alternatively: real OS env vars prefixed `ASTRA_TENANT__<UPPER_ID>__…` override the `.env` file.

### Which values are secrets
- WordPress application password
- LinkedIn access token
- Twitter API key / API secret / access token / access secret / bearer token

### Operator-level keys
- `LLM_API_KEY` — shared by default, per-tenant override allowed. Lives in root `.env`.
- Per-tenant LLM override: set `llm.api_key_env` in `tenant.yaml` pointing at a different env var.

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
- Subsequent LinkedIn distribution attempts for that tenant are skipped with reason `needs_reauth` until the operator runs `astra auth linkedin --tenant <id>` and updates the `.env`.
- `astra health` and `astra tenant list` both surface this state.

## Naming

- Tenant IDs are slugs: `[a-z0-9][a-z0-9-]*[a-z0-9]`, 2–40 chars. Validated at tenant creation.
- Tenant names are free-form UTF-8 for display only.
- Tenant IDs are **immutable** once created. To rename, remove and re-create.
