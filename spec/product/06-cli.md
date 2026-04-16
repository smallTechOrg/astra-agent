# CLI

**Status:** DRAFT

The CLI is the **only** operator interface. Every operator intent must map to a command here. If you find yourself editing SQL by hand or writing one-off scripts, the missing behavior is a spec gap.

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
Creates `config/tenants/<id>/tenant.yaml` with a template and an empty `.env`. The tenant is created with `enabled: false`. ID is validated against the slug regex. Fails if directory already exists.

```
astra tenant list
```
Prints a table:

```
ID            NAME                  ENABLED  STATUS     LAST POLL       PENDING
acme-corp     Acme Corporation      yes      ok         2m ago          0
beta-inc      Beta Inc              yes      degraded   5m ago          3
draft-client  Draft Client          no       -          -               -
```

Columns:
- `STATUS`: `ok` | `degraded` (missing secret, expired token, etc.) | `-` for disabled
- `PENDING`: count of `distribution_records` rows in `pending`/`failed` not yet retried successfully

```
astra tenant enable <id>
astra tenant disable <id>
```
Flip `enabled:` in the tenant's YAML. Requires daemon restart to take effect (warned on stdout).

```
astra tenant remove <id> [--force]
```
Deletes the tenant's config directory and all DB rows scoped to that tenant_id. Prompts for confirmation unless `--force` is passed.

### Manual distribution

```
astra distribute --tenant <id> --wp-post-id <post_id> [--platform linkedin|twitter] [--force]
```
Fetch the named WordPress post and distribute. If a `distribution_records` row exists for `(event, platform)` with `status=sent`, the command refuses unless `--force`. Useful for testing, re-publishing after prompt changes, or catching up after downtime.

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
    acme-corp:  wp-poll(*/5 * * * *), share-sweep(*/10 * * * *), cadence:daily-tech-tips(0 14 * * *)
    beta-inc:   wp-poll(*/5 * * * *), share-sweep(*/10 * * * *)
  Press Ctrl+C to stop.
```

### Health

```
astra health [--tenant <id>]
```
Checks each configured service. With `--tenant`, only that tenant. Without, runs operator-level checks (LLM, DB) and iterates all tenants.

Output:
```
Operator
  Database:       ok
  LLM (groq):     ok

Tenant: acme-corp
  WordPress:      ok
  LinkedIn:       ok
  Twitter:        ok

Tenant: beta-inc
  WordPress:      ok
  LinkedIn:       FAILED — needs_reauth (run: astra auth linkedin --tenant beta-inc)
  Twitter:        ok
```

### Auth

```
astra auth linkedin --tenant <id> --client-id <id> --client-secret <secret> [--port 8989]
```
Runs LinkedIn OAuth2 flow scoped to the named tenant. On success, writes the token into `config/tenants/<id>/.env` under `LINKEDIN_ACCESS_TOKEN=` (creating or updating). Clears `needs_reauth` for the tenant on next daemon reload.

### Introspection

```
astra events --tenant <id> [--limit N]
```
Lists recent `publish_events` with their distribution status:

```
ID   DETECTED      TITLE                          LINKEDIN       TWITTER
42   2m ago        "On Buddhist Emptiness"        sent           sent
41   1h ago        "The Middle Way"               sent           failed (rate_limited)
40   3h ago        "Dharma notes"                 sent           sent
```

```
astra tweets --tenant <id> [--cadence <name>] [--limit N]
```
Lists recent cadence tweets with status.

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

- `astra prompt edit` — edit prompts via CLI. Use a text editor on the prompt file directly.
- `astra tenant rename` — IDs are immutable.
- Interactive TUI / dashboard.
- Remote API for managing tenants over HTTP.
