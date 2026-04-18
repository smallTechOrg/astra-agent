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
Updates `tenants.enabled` in the DB. Requires daemon restart to take effect (warned on stdout).

```
astra tenant remove <id> [--force]
```
Deletes all DB rows scoped to that `tenant_id` (cascades from `tenants` table). Prompts for confirmation unless `--force` is passed.

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
Runs LinkedIn OAuth2 flow scoped to the named tenant. Starts a local callback server on `--port` (default 8989), opens the browser for LinkedIn consent, and on success upserts `LINKEDIN_ACCESS_TOKEN` into `tenant_secrets` for that tenant. Clears `destination_state.needs_reauth` for LinkedIn. Requires daemon restart to take effect.

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

### UI server

```
astra ui [--host 127.0.0.1] [--port 8080] [--open]
```
Starts the operator web UI. Serves the pre-built Next.js static export (bundled in the Python package) and a FastAPI JSON API on the same port. Behavior:

- Binds to `127.0.0.1:8080` by default (loopback only).
- `--open` opens the default browser to `http://<host>:<port>` after startup.
- **Refuses to start** with a non-loopback `--host` unless `ASTRA_UI_PASSWORD` is set in `config/.env`. This prevents accidental open exposure.
- Does not start or stop `astra run`. The two processes are independent and share the PostgreSQL database.

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
- `astra reload` — hot-reload config without restart. Planned; not yet spec'd.
