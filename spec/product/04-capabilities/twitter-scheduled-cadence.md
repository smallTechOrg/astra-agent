# Capability: Twitter scheduled cadence

**Status:** DRAFT
**Component:** `TwitterCadence` (implements the `Cadence` abstraction)

## Purpose

Keep a tenant's X/Twitter feed active between blog announcements by posting one LLM-generated tweet per cadence tick, on a cadence-configured cron, about a cadence-configured topic, avoiding repetition of recent cadence tweets.

## Trigger

Scheduled — one job per `(tenant, cadence_name)` on the cadence's own cron expression. A tenant may configure multiple independent cadences (e.g. `daily-tips` at `0 14 * * *` and `hourly-quote` at `0 * * * *`).

The cadence is **fully independent** of blog-announcement distribution. It has no knowledge of recent announcements and its schedule is not adjusted around them.

## Behavior

1. Load the tenant's cadence config for this cadence_name: `prompt` name, `feedback_last_n` (default 20), `enabled`. If disabled, skip.
2. Verify the tenant's Twitter destination is configured and not in "degraded" state from a prior 401. If degraded, record a `skipped` `scheduled_tweets` row and exit.
3. Read the last `feedback_last_n` rows from `scheduled_tweets` for `(tenant_id, cadence_name)` ordered by `posted_at DESC`, where `status = "sent"`. Extract the tweet texts.
4. Resolve the prompt: tenant override at `config/tenants/<id>/prompts/{prompt}.txt` else operator default at `prompts/{prompt}.txt`. The prompt is expected to contain two template variables:
   - `{recent_tweets}` — newline-joined list of recent tweets, or the literal string `(none yet)` if empty.
   - `{tenant_name}` — the tenant's display name.
   Additional custom variables defined by the prompt author are allowed; they must have defaults or be declared as required in the prompt's frontmatter (see [`08-prompts.md`](../08-prompts.md)).
5. Call the LLM with temperature ≥ 0.8 (diverse output for variety). Ask for a single tweet ≤ 280 characters, no markdown, no quotes around the output, no URL unless the prompt explicitly says to include one.
6. Post-process:
   - Strip quotes/whitespace.
   - If > 280 chars, truncate to 279 + `…`.
   - If < 20 chars, record `failed` with `llm_output_too_short` and exit.
7. POST to X via `POST /2/tweets` with `{ "text": "{tweet_text}" }`, OAuth 1.0a using the tenant's keys.
8. On success: insert `scheduled_tweets` row `(tenant_id, cadence_name, text, platform_post_id, status="sent", posted_at=now())`.
9. On failure: insert `scheduled_tweets` row `(…, status="failed", error=..., posted_at=now())`. Do not retry within the tick. Next cron tick is the next attempt.

## Inputs

**Config** (from `tenant.yaml`):
- `cadences[]` — list of cadence entries. Each has:
  - `name` — unique within the tenant; used as `cadence_name` in DB.
  - `cron` — cron expression.
  - `prompt` — prompt name.
  - `feedback_last_n` — integer, default 20. How many recent tweets to feed back.
  - `enabled` — bool, default `true`.

**State**:
- The last N rows from `scheduled_tweets` for `(tenant_id, cadence_name)`.

**External**:
- LLM, X API.

## Outputs

**DB writes**:
- One `scheduled_tweets` row per tick (either `sent`, `failed`, or `skipped`).

**External calls**:
- One LLM call, one X POST call (unless skipped).

**Logs**:
- `cadence_tick_started` with tenant_id, cadence_name.
- `cadence_tweet_generated` with length.
- `cadence_tweet_sent` with platform_post_id.
- `cadence_tweet_failed` with error.
- `cadence_tweet_skipped` with reason.

## Failure modes

| Failure | Response |
|---|---|
| Cadence disabled | Skip silently — scheduler should not have fired. If it did (race on reload), record `skipped` with `cadence_disabled`. |
| Tenant Twitter degraded | Record `skipped` with `destination_degraded`. |
| LLM call fails | Record `failed`. Next cron tick retries. |
| LLM output too short / too repetitive vs recent | Length check at step 6. Semantic repetition is the prompt's responsibility — the system does not re-check. |
| X 401 | Record `failed`, mark destination degraded. |
| X 429 | Record `failed` with `rate_limited`. Respect `x-rate-limit-reset` — skip further cadence ticks for this tenant until then. |
| X 403 (duplicate) | Record `failed` with `duplicate_content`. Prompt needs tuning or `feedback_last_n` increased. No auto-retry. |
| X 5xx | Record `failed`. Next tick retries. |

## Out of scope

- **Coordinating with blog announcements.** Explicit. Cadences do not pause, advance, or skip based on announcements.
- **Threads or multi-tweet posts.** One tweet per tick.
- **Quoting or reply-chaining another tweet.** Top-level tweets only.
- **Media attachments.** Text only.
- **Time-of-day awareness in the prompt.** If the prompt wants "good morning tweet," the prompt author encodes that. The system doesn't pass clock info.
- **Cross-cadence deduplication.** Each cadence's repetition-avoidance is scoped to its own name. Two cadences on the same tenant can accidentally repeat each other; that's an operator-level prompt-design concern.
