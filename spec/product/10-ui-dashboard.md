# UI Dashboard

**Status:** DRAFT

## Purpose

The operator web UI provides a guided, browser-based interface for onboarding tenants, monitoring distribution health, and triggering manual actions. It complements the CLI ([`06-cli.md`](06-cli.md)) — every action here has a CLI equivalent. The CLI is complete; the UI is additive.

## Audience

Operators only. Tenants never interact with this UI. There is no tenant-facing endpoint.

## Hosting

`astra ui` starts a FastAPI process that:

- Serves the pre-built Next.js static export (bundled in the Python package under `astra/ui/out/`) via `StaticFiles`.
- Exposes a JSON API under `/api/` consumed by the frontend.
- Binds to `127.0.0.1:8080` by default (loopback only).
- Accepts `--host`, `--port`, `--open` flags (see [`06-cli.md`](06-cli.md#ui-server)).
- **Refuses to start** with a non-loopback `--host` unless `ASTRA_UI_PASSWORD` is set in `config/.env`.

The UI and the daemon (`astra run`) are separate processes sharing the same PostgreSQL database. The UI never talks to the daemon process directly — it reads/writes the DB.

## Tech stack

- **Backend**: FastAPI (Python), `asyncpg`, same PostgreSQL DB as the daemon.
- **Frontend**: Next.js 15 (static export), React 19, TypeScript 5, Tailwind CSS 4.
- **Build**: npm + Turbopack for development; `next build` for production. Built in CI; `out/` ships inside the Python package. Operators do not need Node.js.

See [`../engineering/tech-stack.md`](../engineering/tech-stack.md) for the full library list.

## Auth

The UI uses a single operator password stored in `config/.env` as `ASTRA_UI_PASSWORD`.

- All routes (except the login page) require an authenticated session.
- Sessions are server-side (signed cookie). Browser never stores `ASTRA_UI_PASSWORD`.
- All state-changing POST/PUT/DELETE endpoints require a CSRF token.
- Secret fields (WordPress password, Twitter keys, LinkedIn token) are rendered `type=password`, never pre-filled, and never returned from the API after save. The API returns presence only: `"set"` or `"empty"`.
- If `ASTRA_UI_PASSWORD` is not set and the host is loopback, the UI starts in **no-auth mode** (development convenience). This is logged as a warning on startup.

Reverse-proxy auth (`ui.trust_proxy_header: "X-Remote-User"` in `operator.yaml`) is planned but deferred to v2. In v1, use `ASTRA_UI_PASSWORD` and keep the UI on loopback or behind a trusted tunnel.

## Screen map

Every screen maps to one or more CLI commands. The underlying DB operations are identical.

| Screen | CLI equivalent |
|---|---|
| Dashboard home | `astra tenant list` + `astra health` |
| Tenant detail | `astra events --tenant <id>` + `astra health --tenant <id>` |
| Tenant onboarding wizard | `astra tenant add`, configure via DB, `astra auth linkedin` |
| Cadence management | `astra cadence run --tenant <id> --name <name>` |
| Prompt editor | (no CLI equivalent — DB-only write path) |
| Manual distribute | `astra distribute --tenant <id> --wp-post-id <id>` |
| Tenant enable/disable/delete | `astra tenant enable/disable/remove` |
| Daemon status | Read-only mirror of `astra run` startup state |

## Tenant onboarding wizard

Guided step-by-step flow. Each step validates before advancing. The tenant is created in `enabled: false` state; the final step offers to enable it.

1. **Identity** — Enter tenant ID (slug, validated against `[a-z0-9][a-z0-9-]*[a-z0-9]`) and display name. Fails if ID already exists.
2. **WordPress source** — Enter site URL and WordPress username. Enter application password (write-only field). Validation: attempt a WP REST API call; show success or error before advancing.
3. **LinkedIn destination** (optional, skip if not needed) — Enter LinkedIn organization ID. Click "Connect LinkedIn": initiates OAuth2 flow using `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` from `config/.env`. The browser redirects to LinkedIn consent and back to the UI callback. On success, `LINKEDIN_ACCESS_TOKEN` is written to `tenant_secrets`. No-JS fallback: display `astra auth linkedin --tenant <id>` command for the operator to run in a terminal.
4. **Twitter destination** (optional, skip if not needed) — Enter four API key fields (API key, API secret, access token, access secret). All write-only. Validates by making a Twitter API identity call.
5. **Cadences** (optional) — Add one or more cadence jobs. Fields: name, cron expression, prompt name, feedback_last_n, enabled toggle. Cron is validated client-side and server-side.
6. **Review** — Summary of all inputs. Secrets shown as `••••••` (presence indicator). Edit links return to the relevant step.
7. **Save** — Writes `tenant_config`, `tenant_secrets`, and `cadences` rows atomically. Shows "Restart daemon to apply" banner. Offers "Enable tenant" toggle.

LinkedIn `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are operator-level credentials configured once in `config/.env`. They are not per-tenant and are not editable in the UI.

## Secret handling rules

These rules apply to all UI surfaces, not just the wizard. They are enforced at the API layer.

1. Secret inputs are `type=password` and are never pre-filled.
2. The API never returns secret values after they are saved. Presence is indicated as `"set"` or `"empty"`.
3. The browser never stores secrets in `localStorage`, `sessionStorage`, or cookies (only the session token is in a cookie).
4. Write-only: the only direction for a secret is operator → server. Never server → browser.

These rules are the UI expression of [`../engineering/secret-hygiene.md`](../engineering/secret-hygiene.md). If a rule conflicts, `secret-hygiene.md` is authoritative.

## Observability surface

The UI exposes data already present in the DB. No new tables beyond `prompts`.

- **Tenant list**: `tenants` + `tenant_config` + latest `destination_state` per tenant.
- **Tenant detail**: `publish_events` with joined `distribution_records`; `scheduled_tweets` for cadences; `destination_state`.
- **Daemon status**: read-only — last startup time and scheduled job list (read from a `daemon_heartbeat` row the daemon writes on startup; see Failure modes below).
- No live log streaming in v1. No Prometheus/Grafana integration.

## Prompt editor

The UI provides a screen for editing prompts stored in the `prompts` table (see [`07-data-model.md`](07-data-model.md#schema) and [`08-prompts.md`](08-prompts.md)).

### Two scopes

- **Operator defaults** — prompts where `tenant_id IS NULL`. Visible to all tenants as fallback. Edited from a top-level "Prompts" screen.
- **Tenant overrides** — prompts where `tenant_id = <id>`. Edited from the tenant detail screen under a "Prompts" tab. When a tenant override exists, it takes precedence over the operator default.

### Screen behavior

- Lists all prompts for the current scope (operator or tenant).
- Each prompt row shows: name, first ~80 chars of content, `updated_at`.
- Click to edit: opens a plain-text editor (monospace `<textarea>`). The `# variables:` header and `---` separator are part of the editable content — no structured form, just text.
- "New prompt" button: enter a name (validated: `[a-z0-9_]+`), then edit content.
- "Delete" button on tenant overrides (falls back to operator default). Operator defaults cannot be deleted if they are one of the two required prompts (`linkedin_announcement`, `twitter_announcement`).
- "Reset to default" on tenant overrides: deletes the tenant row, showing the operator default content for reference.

### API endpoints

All under `/api/`:

- `GET /api/prompts?tenant_id=<id>` — list prompts for a tenant (includes resolved operator defaults where no override exists, marked `scope: "operator"`).
- `GET /api/prompts?scope=operator` — list operator-level defaults only.
- `GET /api/prompts/{name}?tenant_id=<id>` — get single prompt content (resolved: tenant override if exists, else operator default).
- `PUT /api/prompts/{name}?tenant_id=<id>` — create or update a tenant prompt override. Body: `{content: "..."}`.
- `PUT /api/prompts/{name}?scope=operator` — create or update an operator default. Body: `{content: "..."}`.
- `DELETE /api/prompts/{name}?tenant_id=<id>` — delete a tenant override.

All write endpoints require CSRF token. Prompt content is never treated as a secret — it is readable and editable.

## Failure modes

| Failure | UI behavior |
|---|---|
| UI server unavailable | CLI still works; UI has no impact on daemon |
| DB unreachable | UI shows error banner; never silently serves stale state |
| Daemon not running | Dashboard shows "Daemon offline" banner; tenant data is readable but job status may be stale |
| OAuth popup blocked | No-JS fallback: show `astra auth linkedin` CLI command |
| Non-loopback bind without password | `astra ui` refuses to start with a clear error message |

## Out of scope

- **Tenant-facing UI.** This dashboard is for operators only.
- **Hosted SaaS control plane.** Loopback by default; operators who expose it accept the responsibility.
- **Cross-tenant views** beyond the operator tenant list and aggregate health.
- **Live log streaming or metrics dashboards** (Prometheus, Grafana, etc.).
- **UI plugin or theme system.** New screens land as in-tree spec-first additions to this file.
- **Per-operator user accounts.** Single operator password for v1. Multi-operator support is a future spec revision.
- **Changing the four abstractions** (`Source`, `Destination`, `Cadence`, `LLMClient`). The UI reads/writes config and state; it does not redefine the domain.
