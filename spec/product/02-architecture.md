# Architecture

**Status:** DRAFT

## Component diagram

```
  Operator surfaces
  ─────────────────────────────────────────────────────────
  ┌──────────────────────┐    ┌──────────────────────────┐
  │   astra run          │    │   astra ui               │
  │   (AstraDaemon)      │    │   (FastAPI + Next.js UI) │
  │   one process,       │    │   one process,           │
  │   schedules N tenants│    │   serves operator UI     │
  └──────────┬───────────┘    └────────────┬─────────────┘
             │                             │
             └──────────────┬──────────────┘
                            │  reads/writes
                  ┌─────────▼──────────────────────────────┐
                  │            PostgreSQL DB               │
                  │  tenants · tenant_config               │
                  │  tenant_secrets · cadences             │
                  │  source_state · destination_state      │
                  │  publish_events · distribution_records │
                  │  scheduled_tweets                      │
                  └────────────────────────────────────────┘

  AstraDaemon internals
  ─────────────────────────────────────────────────────────
                  ┌──────────────────────────────────────────────┐
                  │                  AstraDaemon                 │
                  └──────────────────────────────────────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
     ┌────────▼────────┐      ┌─────────▼────────┐      ┌─────────▼────────┐
     │ TenantRunner A  │      │ TenantRunner B   │      │ TenantRunner …   │
     └────────┬────────┘      └──────────────────┘      └──────────────────┘
              │
     ┌────────┼────────────────────────────────────┐
     │        │                                    │
 ┌───▼───┐ ┌──▼──────────────┐       ┌─────────────▼───────────┐
 │Source │ │  Distributor    │       │  CadenceRunner(s)       │
 │(WP)   │─▶ (per publish    │       │  (per cadence config,   │
 │poll   │ │  event)         │       │   independent schedule) │
 └───────┘ └──────┬──────────┘       └─────────────┬───────────┘
                  │                                │
         ┌────────┼──────────┐                     │
         │        │          │                     │
    ┌────▼───┐ ┌──▼────┐ ┌───▼─────────┐     ┌─────▼─────┐
    │LinkedIn│ │Twitter│ │(future)     │     │Twitter    │
    │Dest    │ │Dest   │ │  Mastodon…  │     │Dest       │
    └────────┘ └───────┘ └─────────────┘     └───────────┘
```

## Operator surfaces

Astra has two operator-facing surfaces, both thin wrappers over the same PostgreSQL database and domain layer:

- **CLI** (`astra <command>`) — scriptable, composable, complete. See [`06-cli.md`](06-cli.md).
- **UI** (`astra ui`) — guided web interface for onboarding, monitoring, and manual actions. See [`10-ui-dashboard.md`](10-ui-dashboard.md).

Both surfaces are first-class. Neither is a subset of the other: the CLI is better for automation and scripting; the UI is better for initial setup and day-to-day monitoring.

## Layers and abstractions

Astra is built on four abstractions. **Everything extensible lives behind these.** See [`09-extensibility.md`](09-extensibility.md) for how to add new ones.

### `Source`
Produces publish events. Contract:
- `async poll(tenant) -> list[PublishEvent]` — returns events not yet seen.
- Must be idempotent: calling poll twice never returns the same `(source_post_id)` twice after the first has been persisted.
- Today's only implementation: `WordPressSource`.

### `Destination`
Publishes a single post to a specific platform endpoint for a specific tenant. Contract:
- `async publish(tenant, event, copy) -> PublishResult` — posts `copy` (text) with a reference to `event` (for URL/context); returns platform post ID or typed failure.
- `async health_check(tenant) -> HealthStatus` — is this destination currently usable for this tenant?
- Today's implementations: `LinkedInOrgDestination`, `TwitterDestination`.

### `Cadence`
An independently-scheduled tweet-posting job with its own prompt and history-awareness. Contract:
- `async tick(tenant, cadence_config) -> Optional[TweetResult]` — called by scheduler on cron. Generates and posts one tweet, or skips with a logged reason.
- Today's only implementation: `TwitterCadence`. Other platforms would require their own `Cadence` variant.

### `LLMClient`
Unchanged from current code. Abstract client over OpenAI / Anthropic / Groq / Gemini. Used by distributors and cadences to generate post copy.

## Data flow: blog announcement

Numbered to make this mechanically verifiable:

1. `AstraDaemon` starts. Loads all tenants from `config/tenants/`. Skips disabled tenants.
2. For each enabled tenant, schedules a `source.poll` job on the tenant's configured cron.
3. At tick: `WordPressSource.poll(tenant)` queries WP REST for posts published after `source_state.last_seen_at`.
4. For each post not already in `publish_events` (uniqueness on `(tenant_id, source_name, source_post_id)`), insert a row. Update `source_state.last_seen_at`.
5. For each new `publish_event`, the runner enqueues a distribution task per enabled destination (LinkedIn, Twitter).
6. Each distribution task: generate copy via LLM, call the destination's `publish()`, insert a `distribution_records` row (`pending` → `sent` / `failed`). The unique constraint on `(publish_event_id, platform)` prevents double-posting on restart.
7. Failures on one destination do not affect the other. Failures in one tenant do not affect another.

## Data flow: scheduled cadence

1. At daemon start, each tenant's enabled `cadence` configs register their own cron jobs.
2. At tick: `TwitterCadence.tick(tenant, cadence_config)`:
   - Reads the last N `scheduled_tweets` rows for `(tenant_id, cadence_name)`.
   - Builds an LLM prompt: topic + "avoid repeating these: [recent tweets]".
   - Generates one tweet (≤280 chars).
   - Posts via Twitter destination.
   - Inserts `scheduled_tweets` row.
3. If the LLM or Twitter call fails, the tick is recorded as failed and skipped until the next cron tick. No retry within the tick.

## Trust boundaries

| Boundary | Trusted? | Notes |
|---|---|---|
| Operator-written config YAML | Yes | `operator.yaml` is assumed not adversarial. |
| Tenant-provided credentials | Yes, from operator POV | Stored in `tenant_secrets` table; never in YAML. |
| UI HTTP requests | Yes (authenticated) | UI binds loopback by default; all state-changing endpoints require the operator session. |
| WordPress REST API responses | No | Validated against response models before use. Untrusted HTML is never executed. |
| LinkedIn / Twitter API responses | No | Validated; errors mapped to typed failures. |
| LLM output | No | Length-checked, truncated if needed, never executed. |

## Process model

- **Daemon** (`astra run`): single async Python process. One shared `asyncio` event loop. Scheduler: APScheduler's `AsyncIOScheduler`.
- **UI server** (`astra ui`): separate async Python process running FastAPI. Serves the pre-built Next.js static export and a JSON API over the same PostgreSQL database.
- **Persistence**: PostgreSQL, accessed via `asyncpg`. Both processes connect to the same DB. Daemon writes tenant state; UI reads state and writes tenant config/secrets.
- Concurrency across tenants is achieved by cooperative async scheduling, not threads. A slow WP site for tenant A yields to other tenants' jobs.

## What lives where in code (contractually)

The spec does not dictate file layout, with one exception: **the four abstractions above each live in their own module and expose nothing but their abstract interface plus concrete implementations**. This is contractual because extensibility depends on it — [`09-extensibility.md`](09-extensibility.md) documents how new implementations plug in.
