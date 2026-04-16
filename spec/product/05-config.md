# Configuration

**Status:** DRAFT

## File layout

```
config/
├── operator.yaml              # Operator-wide settings (LLM, log level, db path)
├── .env                       # Operator-wide secrets (LLM_API_KEY, etc.)  [gitignored]
└── tenants/
    └── <tenant-id>/
        ├── tenant.yaml        # Per-tenant config: source, destinations, cadences
        ├── .env               # Per-tenant secrets                         [gitignored]
        └── prompts/           # Optional per-tenant prompt overrides
            ├── linkedin_announcement.txt
            ├── twitter_announcement.txt
            └── twitter_cadence_<name>.txt

prompts/                       # Operator-wide default prompts (fallback)
├── linkedin_announcement.txt
├── twitter_announcement.txt
└── twitter_cadence_<name>.txt
```

`state/astra.db` is the SQLite file. Not in `config/` because it's derived state, not configuration.

## Precedence

For any value, precedence is (highest wins):

1. OS env var (e.g. `ASTRA_TENANT__ACME__LINKEDIN__ACCESS_TOKEN`)
2. Per-tenant `.env` file
3. Operator `.env` file
4. Per-tenant `tenant.yaml`
5. Operator `operator.yaml`
6. Built-in defaults

Secrets (anything named `*_token`, `*_password`, `*_secret`, `*_key`) may only come from env sources (1–3). Putting a secret in YAML is a configuration error and Astra rejects the tenant at load time.

## `operator.yaml`

```yaml
# config/operator.yaml

llm:
  provider: "groq"                # openai | anthropic | groq | gemini
  model: "llama-3.3-70b-versatile"
  temperature: 0.8
  max_tokens: 2048
  # api_key comes from env: LLM_API_KEY

database_path: "state/astra.db"
log_level: "info"                 # debug | info | warning | error

daemon:
  share_sweep_cron: "*/10 * * * *"   # periodic retry of unsent distributions
  startup_grace_seconds: 5           # delay before first scheduled run after boot
```

## `tenants/<id>/tenant.yaml`

```yaml
# config/tenants/acme-corp/tenant.yaml

id: acme-corp                      # must match directory name
name: "Acme Corporation"
enabled: true

source:
  type: wordpress
  url: "https://blog.acme.com"
  username: "admin"
  app_password_env: "WP_APP_PASSWORD"
  poll_cron: "*/5 * * * *"

destinations:
  linkedin:
    enabled: true
    organization_id: "12345678"
    access_token_env: "LINKEDIN_ACCESS_TOKEN"
    prompt: "linkedin_announcement"

  twitter:
    enabled: true
    api_key_env: "TWITTER_API_KEY"
    api_secret_env: "TWITTER_API_SECRET"
    access_token_env: "TWITTER_ACCESS_TOKEN"
    access_secret_env: "TWITTER_ACCESS_SECRET"
    announcement_prompt: "twitter_announcement"

cadences:
  - name: "daily-tech-tips"
    cron: "0 14 * * *"              # daily 14:00 UTC
    prompt: "twitter_cadence_daily_tech_tips"
    feedback_last_n: 20
    enabled: true
  - name: "hourly-startup-quote"
    cron: "15 * * * *"              # every hour at :15
    prompt: "twitter_cadence_hourly_startup_quote"
    feedback_last_n: 50
    enabled: false

# Optional: per-tenant LLM override
# llm:
#   api_key_env: "ACME_LLM_API_KEY"
#   model: "claude-sonnet-4-6"
```

Env-var names referenced in `tenant.yaml` (e.g. `WP_APP_PASSWORD`) are resolved against the **tenant's own `.env`** first, then OS env. This keeps each tenant's secrets namespaced to their directory — the operator doesn't have to prefix them.

## `tenants/<id>/.env`

Gitignored. One flat file, plain `KEY=value`:

```
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
LINKEDIN_ACCESS_TOKEN=AQUz...
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
```

Values with spaces don't need quoting (standard dotenv parsing).

## Config validation

At daemon startup, for each tenant:

1. **Schema check**: `tenant.yaml` matches the pydantic model. Unknown keys are a warning, not a fatal error (forward-compat for spec additions).
2. **ID consistency**: `id` field matches directory name. Mismatch is fatal for this tenant.
3. **Secret resolution**: every `*_env` pointer resolves to a non-empty value. Missing secrets for an *enabled* destination mark the tenant "degraded"; missing secrets for a *disabled* destination are OK.
4. **Cadence uniqueness**: no two cadences in the same tenant have the same `name`.
5. **Cron validity**: all `*_cron` fields parse as valid 5-field cron expressions.
6. **Source type known**: `source.type` must match a registered source (today: only `wordpress`).

Failures in validation for one tenant log a structured error and mark that tenant degraded. **Other tenants load normally.**

## Reload semantics

- The daemon does not watch config files live. A restart is the only way to pick up changes.
- Planned future capability: `astra reload` sends SIGHUP, triggers re-read and safe re-registration of jobs. Out of scope for v1 of the rebuild.

## Env var naming for operator override

For one-off overrides without editing files, the full-path env convention is:

```
ASTRA_TENANT__<UPPER_ID>__<SECTION>__<KEY>
```

Example: `ASTRA_TENANT__ACME_CORP__DESTINATIONS__LINKEDIN__ENABLED=false` to disable LinkedIn for the `acme-corp` tenant without editing YAML.

Tenant ID dashes become underscores in the env-var path (`acme-corp` → `ACME_CORP`).

## Deleted config surface

These keys existed in the old Astra and are **gone** — referencing them in any YAML is a load-time error:

- Anything under `wordpress:` at the root (was global, now per-tenant under `source:`).
- `twitter_bot.*` — engagement is out of scope.
- `scheduler.post_cron`, `scheduler.engage_cron` — no longer exists.
- `pollinations_api_key` — image generation removed.
- `linkedin.access_token` at root — now per-tenant under `destinations.linkedin`.
