# Twitter blog announcement (SUPERSEDED)

**Status:** SUPERSEDED — this per-platform capability spec is replaced by the agentic model. Platform knowledge is runtime data, not a coded capability. See [`platform-knowledge-seeds.md`](platform-knowledge-seeds.md#x--twitter) for the researched platform details.

The feasibility research below is preserved for reference. The Twitter section in `platform-knowledge-seeds.md` is the canonical source.

## Purpose

Announce a newly-published WordPress post on the tenant's X/Twitter account as a single tweet.

## Feasibility

**BLOCKER as of April 2026.**

| Question | Finding |
|---|---|
| API access model | X API v2 `POST /2/tweets` requires the **Basic** tier or higher. The Free tier is **read-only** (post lookup, user lookup) — it cannot create tweets. Basic costs **$200/month** (as of 2025). Pay-per-use credits are an alternative but similarly expensive at scale. |
| Approval lead time | None beyond payment — Basic access is instant once subscribed. |
| Rate limits (Basic) | 50 tweets per user per 24 hours — adequate for distribution + cadence. |
| ToS risks | Automated posting via the API is permitted on paid tiers. The Free tier explicitly prohibits tweet creation. |
| Alternatives | **Bluesky** — AT Protocol has a free, open write API with no paid tier requirement. **Mastodon** — free write API on any instance. Both serve the "developer/tech audience" segment that Twitter historically served. A platform-agnostic `Destination` interface means swapping Twitter for Bluesky/Mastodon is a spec + implementation change, not an architecture change. |

**What would unblock this:** Either (a) X re-introduces free write access, (b) the operator accepts the $200/month cost and the spec is updated to document it as a paid prerequisite, or (c) Twitter is replaced with a free-tier alternative (Bluesky, Mastodon) as the short-form distribution destination.

**Recommendation:** Replace Twitter with Bluesky as the default short-form destination. Add Twitter as an opt-in destination for operators who have a paid X API subscription.

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
