# CLI

**Status:** DRAFT

The CLI is the **complete** operator interface — every operator intent can be performed here. The UI ([`10-ui-dashboard.md`](10-ui-dashboard.md)) is an additive, guided surface over the same operations. If you find yourself editing SQL by hand or writing one-off scripts, the missing behavior is a spec gap.

## Global flags

| Flag | Effect |
|---|---|
| `--json-log` | Emit logs as JSON instead of coloured console output. |
| `--config-dir PATH` | Override `config/` root. Default: `./config` relative to cwd. |
| `-v`, `-vv` | Increase log verbosity (info → debug). |

## Command surface

### Tenant management

```
astra tenant add <id> [--name "Display Name"]
```
Inserts a row into `tenants` and an empty `tenant_config` row. The tenant is created with `enabled: false`. ID is validated against the slug regex. Fails if the ID already exists in the DB.

```
astra tenant list
```
Prints a table:

```
ID            NAME                  ENABLED  STATUS     PLATFORMS   LAST POLL       PENDING
acme-corp     Acme Corporation      yes      ok         3           2m ago          0
beta-inc      Beta Inc              yes      degraded   2           5m ago          1
draft-client  Draft Client          no       -          0           -               -
```

Columns:
- `STATUS`: `ok` | `degraded` (missing secret, expired token, etc.) | `-` for disabled
- `PLATFORMS`: count of enabled `tenant_platforms` rows
- `PENDING`: count of `plan_items` in `pending`/`failed` state

```
astra tenant enable <id>
astra tenant disable <id>
```
Updates `tenants.enabled` in the DB. Requires daemon restart to take effect (warned on stdout).

```
astra tenant remove <id> [--force]
```
Deletes all DB rows scoped to that `tenant_id` (cascades from `tenants` table). Prompts for confirmation unless `--force` is passed.

### Platform management

```
astra platform add --tenant <id> <platform> [--config '{"key": "value"}']
```
Adds a platform to a tenant by inserting a `tenant_platforms` row. Platform is a free-text identifier (e.g. `bluesky`, `mastodon`, `devto`, `linkedin`, `twitter`). Optional `--config` is a JSON object for platform-specific settings. Warns if no platform knowledge exists for this platform globally.

```
astra platform list --tenant <id>
```
Lists enabled platforms for a tenant:

```
PLATFORM    ENABLED  STATUS     CONFIG
bluesky     yes      ok         {"handle": "acme.bsky.social"}
mastodon    yes      ok         {"instance_url": "https://mastodon.social"}
devto       yes      ok         {}
linkedin    yes      degraded   {"profile_type": "personal"}
```

```
astra platform remove --tenant <id> <platform> [--force]
```
Removes a platform from a tenant. Prompts for confirmation unless `--force`.

### Manual distribution

```
astra distribute --tenant <id> --source-content-id <id> [--platform <name>] [--force]
```
Triggers distribution for a specific content item. If a `distribution_plans` row already exists for this event, the command refuses unless `--force`. With `--platform`, distributes to only that platform. Useful for testing, re-publishing, or catching up.

```
astra cadence run --tenant <id> --name <cadence_name>
```
Trigger one tick of a named cadence immediately, out of schedule. Logs and persists like a normal tick. Fails if cadence is disabled (unless `--force`).

### Daemon

```
astra run [--tenant <id>...]
```
Starts the daemon. With no `--tenant`, runs all enabled tenants. With one or more `--tenant`, runs only those. SIGINT/SIGTERM triggers a graceful shutdown: in-flight jobs complete, scheduler stops, DB connection closes.

Startup output:
```
Astra v2.0 started
  Tenants loaded: 3 (2 enabled, 1 disabled)
  Jobs scheduled: 7
    acme-corp:  wp-poll(*/5 * * * *), sweep(*/10 * * * *), cadence:daily-tech-tips(0 14 * * *)
    beta-inc:   wp-poll(*/5 * * * *), sweep(*/10 * * * *)
  Web-scraper:  connected (http://localhost:3000)
  Press Ctrl+C to stop.
```

### Health

```
astra health [--tenant <id>]
```
Checks each configured service. With `--tenant`, only that tenant. Without, runs operator-level checks and iterates all tenants.

Output:
```
Operator
  Database:       ok
  LLM (groq):     ok
  Web-scraper:    ok (http://localhost:3000)

Tenant: acme-corp
  WordPress:      ok
  bluesky:        ok
  mastodon:       ok
  devto:          ok

Tenant: beta-inc
  WordPress:      ok
  linkedin:       FAILED — missing secret LINKEDIN_ACCESS_TOKEN
  bluesky:        ok
```

### Introspection

```
astra events --tenant <id> [--limit N]
```
Lists recent `publish_events` with their distribution plan status:

```
ID   DETECTED      TYPE   TITLE                          PLAN STATUS   PLATFORMS
42   2m ago        blog   "On Buddhist Emptiness"        completed     bluesky:sent mastodon:sent devto:sent
41   1h ago        blog   "The Middle Way"               partial       bluesky:sent mastodon:failed devto:sent
40   3h ago        media  "Temple gallery"               completed     bluesky:sent mastodon:sent
```

```
astra plan show <plan_id>
```
Shows full detail for a distribution plan: content summary, each plan item with copy, reasoning, status, and tool used.

```
astra trace show <plan_id> [--item <platform>] [--limit N]
```
Shows the action trace for a plan or a specific plan item. This is the primary debugging command.

Output:
```
Plan #42 — "On Buddhist Emptiness" (acme-corp)
  Status: completed

  [bluesky] 3 actions, 1.2s total
    1. knowledge_read  "Read Bluesky API knowledge"                          2ms
    2. llm_call        "Generated Bluesky post (247 chars)"                 890ms
    3. http_request    "POST bsky.social/xrpc/com.atproto.repo.createRecord" 312ms  → 200

  [mastodon] 3 actions, 1.5s total
    1. knowledge_read  "Read Mastodon API knowledge"                         1ms
    2. llm_call        "Generated Mastodon post (412 chars)"                950ms
    3. http_request    "POST mastodon.social/api/v1/statuses"               520ms  → 200
```

With `--verbose` or `-v`, shows full input/output for each trace entry.

```
astra cadence-posts --tenant <id> [--cadence <name>] [--limit N]
```
Lists recent cadence-generated posts with status.

### Knowledge management

```
astra knowledge list [--platform <name>]
```
Lists platform knowledge entries. Without `--platform`, lists all. Shows access method, content constraints, and lesson count.

```
astra knowledge show <platform> [--tenant <id>]
```
Shows full knowledge entry for a platform. With `--tenant`, shows the tenant override if one exists plus the global default for comparison.

### UI server

```
astra ui [--host 127.0.0.1] [--port 8080] [--open]
```
Starts the operator web UI. Serves the pre-built Next.js static export (bundled in the Python package) and a FastAPI JSON API on the same port. Behavior:

- Binds to `127.0.0.1:8080` by default (loopback only).
- `--open` opens the default browser to `http://<host>:<port>` after startup.
- **Refuses to start** with a non-loopback `--host` unless `ASTRA_UI_PASSWORD` is set in `config/.env`. This prevents accidental open exposure.
- Does not start or stop `astra run`. The two processes are independent and share the PostgreSQL database.

### Operator config

```
astra config show
```
Prints the current operator config from the `operator_config` table:

```
LLM provider:           groq
LLM model:              llama-3.3-70b-versatile
LLM temperature:        0.8
LLM max tokens:         2048
Log level:              info
Sweep cron:             */10 * * * *
Startup grace seconds:  5
Web-scraper URL:        http://localhost:3000
```

```
astra config set <key> <value>
```
Updates a single operator config key. Valid keys: `llm_provider`, `llm_model`, `llm_temperature`, `llm_max_tokens`, `log_level`, `sweep_cron`, `startup_grace_seconds`, `web_scraper_url`. Requires daemon restart to take effect (warned on stdout).

### Version

```
astra version
```
Prints `astra-agent x.y.z`.

## Exit codes

- `0` — success
- `1` — operator error (bad args, missing tenant, etc.)
- `2` — runtime error (external service failure, DB error)
- `3` — validation error (config/schema)

## What's not here

These would be convenient but are **explicitly** not in v1 — if you want them, write a spec first:

- `astra prompt edit` — edit prompts via CLI. Use the UI prompt editor.
- `astra knowledge edit` — edit knowledge via CLI. Use the UI knowledge editor.
- `astra tenant rename` — IDs are immutable.
- `astra reload` — hot-reload config without restart. Planned; not yet spec'd.
- `astra plan approve/reject` — plan approval via CLI. Use the UI for the full review workflow.
