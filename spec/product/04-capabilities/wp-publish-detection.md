# Capability: WordPress publish detection

**Status:** DRAFT
**Component:** `WordPressSource` (implements the `Source` abstraction)

## Purpose

Detect newly published WordPress posts for a given tenant by polling the WordPress REST API, and produce `publish_event` records that downstream distribution jobs consume.

## Trigger

Scheduled — once per tenant per tenant's configured `source.poll_cron` (default `*/5 * * * *`, every 5 minutes).

## Behavior

1. Load the tenant's source config: `url`, `username`, `app_password` (from secret env).
2. Read `source_state.last_seen_at` for `(tenant_id, "wordpress")`. If null (first run), use `now() - 7 days` as the cutoff, not epoch — do not backfill years of history on first enable.
3. Query WordPress REST:
   `GET {url}/wp-json/wp/v2/posts?status=publish&after={last_seen_at}&per_page=50&orderby=date&order=asc`
   with Basic auth using `username:app_password`.
4. For each post in the response, in chronological order:
   1. Attempt to insert a `publish_events` row with `(tenant_id, "wordpress", post.id, post.title.rendered, post.link, post.excerpt.rendered, post.date_gmt, now())`.
   2. If the insert fails on the unique constraint `(tenant_id, source_name, source_post_id)`, the post was already detected in a prior run — skip silently.
   3. If the insert succeeds, emit a structured log `publish_event_created` with `tenant_id`, `source_post_id`, `title`.
5. After processing the page, update `source_state.last_seen_at` to the `date_gmt` of the most recent post in the response, and `source_state.last_polled_at` to `now()`.
6. If the response returned `per_page` results, the next scheduled tick handles remaining posts. No pagination within a single tick — the next tick picks up from the new `last_seen_at`.

## Inputs

**Config** (from `tenant.yaml`):
- `source.type` — must be `wordpress`.
- `source.url` — WordPress site base URL.
- `source.username` — WordPress username.
- `source.app_password_env` — env var name holding the application password. Default `WP_APP_PASSWORD`.
- `source.poll_cron` — cron expression. Default `*/5 * * * *`.

**State** (from DB):
- `source_state.last_seen_at`

**External**:
- WordPress REST API at `{url}/wp-json/wp/v2/posts`.

## Outputs

**DB writes**:
- New rows in `publish_events` (one per newly-detected post).
- Update to `source_state.last_seen_at` and `last_polled_at`.

**Side effects**:
- None beyond DB writes. Distribution is a separate capability that consumes `publish_events`.

**Logs**:
- `publish_poll_started` with tenant_id.
- `publish_event_created` with tenant_id, source_post_id, title (one per new post).
- `publish_poll_complete` with tenant_id, new_events_count.

## Failure modes

| Failure | Response |
|---|---|
| WordPress unreachable (connection error, DNS, timeout) | Log `wp_poll_failed` with reason. Do not update `last_seen_at`. Next tick retries. |
| Auth failure (401) | Log `wp_auth_failed`. Mark tenant source as "degraded" for this process lifetime (alerting signal). Do not update `last_seen_at`. |
| 5xx from WordPress | Log and retry with exponential backoff within this tick (max 3 attempts). On final failure, proceed as "unreachable". |
| 429 rate-limit | Log and skip this tick. Do not retry within tick. |
| Malformed JSON response | Log `wp_poll_bad_response` with excerpt. Do not update `last_seen_at`. |
| Single post fails to insert (disk full, etc.) | Log per-post error. Continue with next post. `last_seen_at` is only updated to the date of the **last successfully inserted** post, so failed posts are retried next tick. |

## Out of scope

- **Draft detection.** We only emit events for `status=publish`. Drafts are ignored.
- **Update detection.** A post that was published, then edited and re-saved, produces **no** new event. The `publish_events` unique constraint guarantees first-seen-only semantics. Re-distribution of updated posts is an explicit manual action: `astra distribute --tenant <id> --wp-post-id <id> --force`.
- **Non-post content types.** Pages, custom post types, attachments are not detected.
- **Webhooks.** A webhook-based source would be a new implementation of the `Source` interface in a future spec. This capability is polling-only.
- **Category/tag filtering.** All published posts are detected. If the operator needs filtering (e.g. skip posts in category "internal"), that's a future spec extension on `tenant.yaml` and is out of scope here.
