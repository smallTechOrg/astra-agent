# Architecture

**Status:** DRAFT

## Component diagram

```
  Operator surfaces
  ─────────────────────────────────────────────────────────
  ┌──────────────────────┐    ┌──────────────────────────┐
  │   astra run          │    │   astra ui               │
  │   (AstraDaemon)      │    │   (FastAPI + Next.js UI) │
  │   one process,       │    │   serves operator UI +   │
  │   schedules N tenants│    │   trace viewer           │
  └──────────┬───────────┘    └────────────┬─────────────┘
             │                             │
             └──────────────┬──────────────┘
                            │  reads/writes
                  ┌─────────▼──────────────────────────────┐
                  │            PostgreSQL DB               │
                  │  operator_config · operator_secrets    │
                  │  tenants · tenant_config               │
                  │  tenant_secrets · tenant_platforms     │
                  │  platform_knowledge · action_traces    │
                  │  source_state · publish_events         │
                  │  distribution_plans · plan_items       │
                  │  cadences · cadence_posts · prompts    │
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
     ┌────────┼──────────────────────────┐
     │        │                          │
 ┌───▼───┐ ┌──▼────────────────┐ ┌───────▼──────────────┐
 │Source │ │  Agent            │ │ CadenceRunner(s)     │
 │(WP,   │ │  ┌─────────────┐ │ │ (per cadence config, │
 │ etc.) │ │  │ LLM         │ │ │  independent sched)  │
 └───────┘ │  │ (reasoning) │ │ └───────┬──────────────┘
           │  └──────┬──────┘ │         │
           │  ┌──────▼──────┐ │         │
           │  │ Tools       │ │         │
           │  │ • http      │ │     uses same
           │  │ • browser   │ │     Agent + Tools
           │  │ • knowledge │ │         │
           │  └──────┬──────┘ │         │
           │  ┌──────▼──────┐ │         │
           │  │ Action Trace│ │         │
           │  │ (every step │ │         │
           │  │  recorded)  │ │         │
           │  └─────────────┘ │         │
           └──────────────────┘         │
                  │                     │
         ┌────────▼──────────┐          │
         │DistributionPlan   │          │
         │ (approval queue   │          │
         │  if configured)   │          │
         └────────┬──────────┘          │
                  │ execute via tools   │
      ┌───────────┼───────────┐         │
      │           │           │         │
 ┌────▼────┐ ┌───▼────┐ ┌────▼────┐    │
 │ HTTP    │ │Browser │ │ Future  │    │
 │ tool    │ │ tool   │ │ tools   │    │
 │ (APIs)  │ │(web-   │ │         │    │
 │         │ │scraper)│ │         │    │
 └─────────┘ └────────┘ └─────────┘    │
```

## Operator surfaces

Astra has two operator-facing surfaces, both thin wrappers over the same PostgreSQL database and domain layer:

- **CLI** (`astra <command>`) — scriptable, composable, complete. See [`06-cli.md`](06-cli.md).
- **UI** (`astra ui`) — guided web interface for onboarding, monitoring, distribution plan review, action trace inspection, and manual actions. See [`10-ui-dashboard.md`](10-ui-dashboard.md).

Both surfaces are first-class. The CLI is better for automation; the UI is better for setup, monitoring, and debugging agent behaviour via the trace viewer.

## Core model: Agent + Tools + Knowledge + Traces

Astra is **not** a plugin system with per-platform adapters. It is an agent that uses generic tools and a runtime knowledge store. This section defines the four pillars.

### The Agent

The agent is the reasoning core. Given a content event and a tenant's configured platforms, it:

1. **Plans** — decides which platforms to target, what copy to generate for each, and which tool (HTTP or browser) to use, based on the platform knowledge store.
2. **Executes** — uses tools to carry out each plan item, recording every action as a trace.
3. **Learns** — when execution succeeds or fails, updates the knowledge store with lessons (e.g. "Bluesky rate limit is 1666/day", "DEV.to requires canonical_url for cross-posts").

The agent uses the tenant's configured LLM for reasoning and copy generation. The LLM is called through the `LLMClient` abstraction (OpenAI / Anthropic / Groq / Gemini).

### Tools

The agent has a fixed set of generic tools. No tool is platform-specific. Platforms are many; tools are few.

| Tool | What it does | Backed by |
|---|---|---|
| `http` | Make HTTP requests (GET, POST, PUT, etc.) with headers, body, auth. | Python `httpx` / `aiohttp` in-process |
| `browser` | Navigate pages, fill forms, click buttons, upload files, read page content. | External `web-scraper` service (Playwright) |
| `knowledge_read` | Read platform knowledge entries for a given platform. | `platform_knowledge` DB table |
| `knowledge_write` | Create or update a platform knowledge entry. | `platform_knowledge` DB table |

The agent decides which tool to use based on the platform knowledge. If a platform has a known API, the agent uses `http`. If a platform has no API or the API is paid, the agent uses `browser`. If knowledge is missing, the agent falls back to `browser` (any platform with a web UI can be posted to).

### Platform Knowledge Store

Platform knowledge is **runtime data in the DB**, not compiled code. The `platform_knowledge` table stores everything the agent knows about how to interact with a platform.

Each knowledge entry is a structured record:

```
platform:       "bluesky"
access_method:  "api"                         # api | browser | both
api_base_url:   "https://bsky.social/xrpc"
api_auth_type:  "bearer_token"                # bearer_token | api_key | oauth2 | app_password
api_post_endpoint: "com.atproto.repo.createRecord"
api_post_schema:   { ... JSON template ... }  # request body template with placeholders
browser_compose_url: "https://bsky.app"       # fallback if API fails
content_constraints:
  max_text_length: 300
  supports_images: true
  max_images: 4
  supports_links: true
  link_preview: true
lessons:
  - "Rate limit: 1666 actions/day per account"
  - "Images must be uploaded as blobs first via com.atproto.repo.uploadBlob"
  - "App password auth: POST /xrpc/com.atproto.server.createSession"
updated_at:     "2026-04-19T..."
```

Key properties:
- **Operator-editable.** The operator can view and edit knowledge entries via the UI or API. This is how platform knowledge is corrected when things change.
- **Seed data.** Astra ships with seed knowledge for common platforms (Bluesky, Mastodon, DEV.to, LinkedIn personal). This is inserted on first migration, same as prompt seeds.
- **Tenant-scoped overrides.** A tenant can override platform knowledge (e.g. a Mastodon instance at a custom URL). Stored as `(tenant_id, platform)` in the knowledge table. Resolution: tenant override → global default.
- **Agent-updatable.** After successful or failed execution, the agent may write lessons to the knowledge store. These are visible in the UI for the operator to review.

### Action Traces

Every action the agent takes is recorded as an **action trace**. This is the core observability and debuggability mechanism.

```
trace_id:       uuid
plan_item_id:   FK → plan_items (nullable — some traces are from planning phase)
plan_id:        FK → distribution_plans
tenant_id:      FK → tenants
sequence:       integer (ordering within a plan item)
action_type:    "llm_call" | "http_request" | "http_response" | "browser_navigate" |
                "browser_fill" | "browser_click" | "browser_upload" | "browser_read" |
                "knowledge_read" | "knowledge_write" | "decision" | "error" | "skip"
summary:        "Generated Bluesky post copy (247 chars)"   # human-readable one-liner
input:          JSONB   # what went into the action (prompt, URL, form field, etc.)
output:         JSONB   # what came back (response, generated text, error, etc.)
duration_ms:    integer
parent_trace_id: uuid (nullable — for nesting, e.g. "browser_navigate" inside "post to Twitter")
created_at:     timestamptz
```

Trace design rules:
1. **Every tool invocation produces a trace.** No silent actions.
2. **LLM calls include the full prompt and response.** The operator can see exactly what the agent was told and what it generated.
3. **HTTP requests include method, URL, status code, and (truncated) body.** Credentials are redacted.
4. **Browser actions include the page URL, the action taken, and the result.** Screenshots are not stored (too heavy for v1), but the page text content is captured on errors.
5. **Decisions include the reasoning.** "Skipping Reddit: content is a blog post and Reddit requires subreddit selection which is not configured for this tenant."
6. **Errors include the full context.** Stack trace, the action that failed, the input that caused it, and what the agent tried next.
7. **Traces are immutable.** Once written, never updated. Append-only.

## `Source`

Produces content events from an external content origin. This is the one hard-coded abstraction — sources require polling logic that is inherently source-specific.

Contract:
- `async poll(tenant) -> list[ContentEvent]` — returns content not yet seen.
- Must be idempotent: calling poll twice never returns the same `(source_content_id)` twice after the first has been persisted.
- `ContentEvent` carries: content type (blog, media), title, body/description, URL (if applicable), images (if any), raw metadata.
- Today's implementations: `WordPressSource`. Future: `MediaUploadSource`, `APITriggerSource`, `RSSSource`.

Sources remain as in-tree Python code because each source has a unique polling protocol. Unlike destinations (which are all "post content to a platform"), sources are structurally different enough to warrant code.

## Data flow: content distribution

This is the core flow. Numbered for mechanical verifiability:

1. `AstraDaemon` starts. Reads operator config from `operator_config` table. Loads all tenants. Skips disabled tenants.
2. For each enabled tenant, schedules a `source.poll` job on the tenant's configured cron.
3. At tick: `Source.poll(tenant)` checks for new content since `source_state.last_seen_at`.
4. For each new content item not already in `publish_events`, insert a row. Update `source_state.last_seen_at`.
5. For each new `publish_event`, invoke the **Agent**:

   **Planning phase** (all traced):
   - a. Agent reads tenant's enabled platforms from `tenant_platforms`.
   - b. For each platform, agent reads `platform_knowledge` (tenant override → global).
   - c. Agent calls LLM with the content + platform knowledge + tenant prompts to: (i) decide if this platform is appropriate for this content type, (ii) generate platform-specific copy.
   - d. Agent creates a `DistributionPlan` with one `PlanItem` per selected platform, plus skip records (with reasons) for unselected platforms.
   - e. Plan and items are persisted to DB. All LLM calls and decisions recorded as action traces.

6. **If approval is required** (tenant config `approval_mode = true`): plan status is set to `pending_approval`. Operator reviews in UI — can edit copy, remove platforms, reject.
7. **If auto-execute** (default): plan status is set to `executing`.

   **Execution phase** (all traced):
   - a. For each `plan_item`, agent reads platform knowledge to determine the tool (HTTP or browser).
   - b. **HTTP tool path**: agent constructs the API request from knowledge (endpoint, auth, body template), executes it, records request/response as traces.
   - c. **Browser tool path**: agent sends instructions to the external `web-scraper` service (navigate to compose URL, fill text, attach media, submit), records each browser action as traces.
   - d. On success: record `plan_item.status = 'sent'`, store `platform_post_id`. Optionally write a lesson to knowledge store.
   - e. On failure: record `plan_item.status = 'failed'`, store error. Write failure lesson to knowledge store (e.g. "API returned 401, token may be expired"). The agent does **not** retry within the same execution — retry is a separate sweep.

8. Plan overall status is derived: `completed` (all sent), `partial` (some failed), `failed` (all failed).
9. Failures on one platform do not affect others. Failures on one tenant do not affect another.

## Data flow: scheduled cadence

Cadences use the same Agent + Tools model:

1. At daemon start, each tenant's enabled `cadence` configs register their own cron jobs.
2. At tick: the agent receives the cadence config (platform, topic, prompt).
   - Reads recent post history for `(tenant_id, cadence_name)`.
   - Calls LLM to generate a post for the cadence's platform (traced).
   - Executes via the appropriate tool (HTTP or browser, based on platform knowledge) (traced).
   - Records the result.
3. If execution fails, the tick is recorded as failed and skipped until the next cron tick.

## Distribution plan lifecycle

```
  new content detected
         │
         ▼
  ┌─────────────────┐
  │   planning      │  ← Agent reasons, generates copy (all LLM calls traced)
  └────────┬────────┘
           │
     ┌─────▼──────┐
     │ approval   │
     │ required?  │
     └─────┬──────┘
       yes │      no
     ┌─────▼───┐  ┌──▼──────────┐
     │pending  │  │ executing   │
     │approval │  └──────┬──────┘
     └────┬────┘         │
     edit │ approve      │
     ┌────▼────┐         │
     │executing│─────────┘  ← Agent uses tools (all actions traced)
     └────┬────┘
          │
     ┌────▼────────┐
     │ completed   │  (all items sent)
     │ partial     │  (some items failed)
     │ failed      │  (all items failed)
     │ rejected    │  (operator rejected)
     └─────────────┘
```

## External tool: web-scraper

The `web-scraper` is an external Playwright-based browser automation service. It is **not** part of Astra — it runs as a separate process/service on the operator's infrastructure.

Astra's `browser` tool communicates with it to:
- Navigate to a URL
- Fill form fields by selector or by content description
- Click buttons
- Upload files
- Read page content (for verification or error detection)

The agent does not hardcode CSS selectors for any platform. Instead:
- Platform knowledge stores hints (compose URL, general form structure).
- The agent sends high-level instructions to the web-scraper (e.g. "fill the main text input with this content").
- If the web-scraper can't find the expected element, the agent reads the page content and adapts — or fails with a traced error.

## Trust boundaries

| Boundary | Trusted? | Notes |
|---|---|---|
| Operator DB config | Yes | `operator_config` is assumed not adversarial. |
| Tenant-provided credentials | Yes, from operator POV | Stored in `tenant_secrets` table; never in YAML. |
| UI HTTP requests | Yes (authenticated) | UI binds loopback by default; all state-changing endpoints require the operator session. |
| Source API responses | No | Validated against response models before use. Untrusted HTML is never executed. |
| LLM-generated copy | Semi-trusted | Used as post content only — never executed as code, never interpolated into SQL. Operator can review (approval mode). |
| LLM tool-use decisions | Semi-trusted | Agent's HTTP/browser calls are constrained to the platform knowledge store's known URLs. No arbitrary URL access. |
| External web-scraper | Yes (operator-deployed) | Runs on operator's infrastructure. Astra trusts its responses. |
| Platform knowledge store | Operator-controlled | Seed data ships with Astra; operator can edit. Agent can append lessons but not modify operator entries. |

## Process model

- **Daemon** (`astra run`): single async Python process. One shared `asyncio` event loop. Scheduler: APScheduler's `AsyncIOScheduler`.
- **UI server** (`astra ui`): separate async Python process running FastAPI. Serves the pre-built Next.js static export and a JSON API over the same PostgreSQL database.
- **Web-scraper** (external): separate process/service. Astra communicates with it over HTTP. Not started or managed by Astra.
- **Persistence**: PostgreSQL, accessed via `asyncpg`. All processes connect to the same DB. Daemon writes state + traces; UI reads state/traces and writes config + knowledge.
- Concurrency across tenants is achieved by cooperative async scheduling, not threads. A slow API call for tenant A yields to other tenants' jobs.

## What lives where

| Concern | Where | Why |
|---|---|---|
| Source polling logic | In-tree Python code (`sources/`) | Each source has a unique protocol; code is unavoidable |
| Platform posting logic | Platform knowledge store (DB) + agent reasoning | Platforms are too numerous and change too often for compiled code |
| Copy generation | LLM at runtime via prompts (DB) | Operator-tunable, tenant-overridable |
| Tool execution | In-tree Python code (`tools/`) | Generic HTTP and browser tools; not platform-specific |
| Action tracing | In-tree Python code (`tracing/`) | Trace recording is a cross-cutting concern |
| Platform knowledge | DB (`platform_knowledge` table) | Runtime data, operator-editable, agent-updatable |
