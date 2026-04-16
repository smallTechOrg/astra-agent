# Capability: LinkedIn distribution

**Status:** DRAFT
**Component:** `LinkedInOrgDestination` (implements the `Destination` abstraction)

## Purpose

Announce a newly-published WordPress post on the tenant's LinkedIn organization page.

## Trigger

A `publish_events` row exists for which `distribution_records` has no row with `platform = "linkedin"`, and the tenant has LinkedIn enabled.

Evaluated immediately after `publish_events` insertion (within the same tenant runner tick), and on a periodic sweep (`share_cron`, default `*/10 * * * *`) to catch any events that were missed due to transient failures.

## Behavior

1. Load the tenant's LinkedIn config: `organization_id`, `access_token` (from secret env), `prompt` name.
2. Check `needs_reauth` flag on the tenant's LinkedIn state. If set, skip with reason `needs_reauth` and record a `skipped` `distribution_records` row.
3. Insert a `distribution_records` row with `status = "pending"` to claim this event. The unique constraint on `(publish_event_id, platform)` means two concurrent attempts cannot both proceed — the loser gets a constraint violation and exits.
4. Build the LLM input from the publish event: `title`, `excerpt`, `url`.
5. Resolve the prompt: tenant-override at `config/tenants/<id>/prompts/{prompt}.txt` if present, else operator default at `prompts/{prompt}.txt`.
6. Call the LLM with the prompt filled in. Target output: 700–3000 characters of LinkedIn-friendly copy, no hashtag spam, no markdown.
7. Truncate to LinkedIn's hard limit (3000 chars) if the LLM overshoots. Do not truncate below 700; if the LLM returns less, accept it.
8. POST to LinkedIn:
   - Endpoint: `https://api.linkedin.com/rest/posts`
   - Auth: `Authorization: Bearer {access_token}`, `LinkedIn-Version: 202401` (or current stable version), `X-Restli-Protocol-Version: 2.0.0`.
   - Body: a `Post` object with `author = urn:li:organization:{organization_id}`, `commentary = {llm_copy}`, `visibility = PUBLIC`, `distribution = { feedDistribution: MAIN_FEED }`, and a `content.article` block carrying `source = {url}`, `title`, `description = {excerpt}`.
9. On success (201): extract the LinkedIn post URN from the `x-restli-id` response header. Update `distribution_records` to `status = "sent"`, `platform_post_id = {urn}`.
10. On failure: update `distribution_records` to `status = "failed"`, store `error` field, log the failure.

## Inputs

**Config** (from `tenant.yaml`):
- `destinations.linkedin.enabled` — must be `true`.
- `destinations.linkedin.organization_id` — numeric LinkedIn org ID.
- `destinations.linkedin.access_token_env` — env var name. Default `LINKEDIN_ACCESS_TOKEN`.
- `destinations.linkedin.prompt` — prompt name. Default `linkedin_announcement`.

**State**:
- A `publish_events` row (tenant-scoped).
- Tenant's `needs_reauth` flag.

**External**:
- LinkedIn Posts API.
- Operator's LLM provider.

## Outputs

**DB writes**:
- One `distribution_records` row, transitioning `pending` → `sent` or `failed`.
- On 401: set tenant's `needs_reauth = true`.

**External calls**:
- One LLM generation call.
- One LinkedIn POST call.

**Logs**:
- `linkedin_distribution_started` with `tenant_id`, `publish_event_id`.
- `linkedin_copy_generated` with length.
- `linkedin_post_sent` with `platform_post_id` on success.
- `linkedin_post_failed` with error on failure.

## Failure modes

| Failure | Response |
|---|---|
| `needs_reauth = true` at start | Skip, record `skipped` with reason, do not call API. |
| LLM call fails | Record `failed` with error. The periodic sweep will retry on the next `share_cron` tick. |
| LLM output empty or < 50 chars | Record `failed` with reason `llm_output_too_short`. Do not retry until next sweep. |
| LinkedIn 401 | Record `failed`, set tenant `needs_reauth = true`, log `linkedin_auth_expired`. No further LinkedIn attempts for this tenant until re-auth. |
| LinkedIn 403 (permission not granted, org access revoked) | Record `failed` with specific error. Mark `needs_reauth` = true. Operator alert. |
| LinkedIn 429 | Record `failed` with `rate_limited`. Next sweep retries. |
| LinkedIn 5xx | Record `failed`. Next sweep retries. |
| LinkedIn 422 (malformed post) | Record `failed` with full response body logged. Do not auto-retry — this is a bug in our code or prompt, not a transient error. |
| Unique-constraint conflict on `distribution_records` insert | Another runner is handling it. Exit silently. |

## Out of scope

- **Personal profile posts.** Explicitly not supported. See [`01-vision.md`](../01-vision.md).
- **Image/video attachments.** The WP post's featured image is not mirrored to LinkedIn in v1. LinkedIn will render a preview card from the article URL via Open Graph tags on the WP site. Image attachment is a separate capability spec if needed later.
- **Scheduled posts.** Astra posts immediately on detection, not at a scheduled time. LinkedIn's API supports scheduled posting; exposing it is out of scope.
- **Comments on behalf of the org.** Not handled.
- **Post editing or deletion.** Distribution is fire-and-forget. If the WP post is edited, Astra does not update the LinkedIn post.
- **Analytics / impression tracking.** Out of scope.
