# Capability: Twitter blog announcement

**Status:** DRAFT
**Component:** `TwitterDestination.publish_announcement` (implements the `Destination` abstraction)

## Purpose

Announce a newly-published WordPress post on the tenant's X/Twitter account as a single tweet.

## Trigger

A `publish_events` row exists for which `distribution_records` has no row with `platform = "twitter"`, and the tenant has Twitter enabled.

Evaluated immediately after `publish_events` insertion, and on the periodic sweep (`share_cron`).

## Behavior

1. Load the tenant's Twitter config: OAuth 1.0a credentials (`api_key`, `api_secret`, `access_token`, `access_secret`), prompt name.
2. Insert `distribution_records` row with `status = "pending"`. Unique constraint on `(publish_event_id, platform)` provides concurrency safety.
3. Build LLM input from the publish event: `title`, `excerpt`, `url`.
4. Resolve prompt: tenant-override or operator default at `prompts/{prompt}.txt`. Default name: `twitter_announcement`.
5. Call the LLM. Ask for tweet copy that **must include the full post URL** and must be ≤ 260 characters of body + URL (the URL counts as its shortened 23 chars on X, but we budget conservatively).
6. Post-process:
   - Strip surrounding quotes, leading/trailing whitespace.
   - If URL is missing, append it with a leading space.
   - If total length > 280 chars, truncate body (not URL) to fit, preserving the URL and a trailing ellipsis `…`.
7. POST to X:
   - Endpoint: `https://api.twitter.com/2/tweets`
   - Auth: OAuth 1.0a with the tenant's four keys.
   - Body: `{ "text": "{tweet_text}" }`.
8. On success (201): extract the tweet ID from `data.id`. Update `distribution_records` to `status = "sent"`, `platform_post_id = {tweet_id}`.
9. On failure: update to `status = "failed"`, store `error`.

## Inputs

**Config** (from `tenant.yaml`):
- `destinations.twitter.enabled` — must be `true`.
- `destinations.twitter.api_key_env` / `api_secret_env` / `access_token_env` / `access_secret_env` — env var names, with defaults documented in [`05-config.md`](../05-config.md).
- `destinations.twitter.announcement_prompt` — default `twitter_announcement`.

**State**:
- A `publish_events` row.

**External**:
- X API v2 `POST /2/tweets`.
- LLM provider.

## Outputs

**DB writes**:
- One `distribution_records` row.

**External calls**:
- One LLM call, one X POST call.

**Logs**:
- `twitter_announcement_started`, `twitter_copy_generated`, `twitter_announcement_sent`, `twitter_announcement_failed`.

## Failure modes

| Failure | Response |
|---|---|
| LLM fails or returns empty | Record `failed`. Next sweep retries. |
| LLM output is garbage (no URL, nonsense) | Length check + URL-presence check; if the fix-up in step 6 cannot produce a valid tweet, record `failed` with reason `invalid_llm_output`. |
| X 401 | Record `failed`. Log `twitter_auth_failed`. Marks tenant's twitter destination as degraded for this process lifetime — operator must fix keys and reload. |
| X 429 | Record `failed` with `rate_limited`. Respect `x-rate-limit-reset` header: skip further Twitter calls for this tenant until that timestamp. |
| X 403 (duplicate content) | Record `failed` with reason `duplicate_content`. Do not auto-retry — the prompt has a repetition bug, or the post was already tweeted manually. |
| X 5xx | Record `failed`. Next sweep retries. |
| Unique-constraint conflict on `distribution_records` insert | Exit silently. |

## Out of scope

- **Threads.** v1 posts exactly one tweet per blog announcement. A "split long post across a thread" capability is a future extension.
- **Media attachments.** No images pulled from the WP post.
- **Scheduled announcements.** Posts immediately on detection.
- **Reply / quote-tweet semantics.** Announcements are top-level tweets.
- **Announcement spacing vs cadence.** The scheduled cadence capability runs on its own cron — it does not know about announcements and will not delay itself. If an announcement and a cadence tick happen within the same minute, both tweets post. That's intentional; decoupling is simpler and has been confirmed.
