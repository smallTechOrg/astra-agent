# Platform knowledge seeds

**Status:** DRAFT

## Purpose

This document captures researched platform details that inform the initial `platform_knowledge` seed data (see [`../07-data-model.md`](../07-data-model.md#schema)). These are not "capabilities" — they are reference material for the operator when seeding the knowledge store via the UI or CLI (see [`../09-extensibility.md`](../09-extensibility.md#adding-a-new-platform)).

The agent uses this knowledge at runtime. No per-platform code exists.

## Bluesky (AT Protocol)

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://bsky.social/xrpc` |
| Auth type | App password (handle + app-specific password) |
| Post endpoint | `com.atproto.repo.createRecord` (collection: `app.bsky.feed.post`) |
| Max text length | 300 characters (grapheme clusters) |
| Supports images | Yes (up to 4, via `com.atproto.repo.uploadBlob`) |
| Supports links | Yes (facets with `app.bsky.richtext.facet#link`) |
| Rate limits | Generous — no known strict per-day post limit for normal use |
| Cost | Free |
| Feasibility | **No blockers.** Free API, instant access, no review process. |

## Mastodon

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://{instance}/api/v1` (instance-specific) |
| Auth type | OAuth2 bearer token (create app → authorize → token) |
| Post endpoint | `POST /api/v1/statuses` |
| Max text length | 500 characters (default; instance-configurable) |
| Supports images | Yes (up to 4, via `POST /api/v2/media`) |
| Supports links | Yes (plain text URLs auto-linked) |
| Rate limits | 300 requests per 5 minutes (default) |
| Cost | Free |
| Feasibility | **No blockers.** Free, open API. Instance URL is per-tenant config. |

## DEV.to

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://dev.to/api` |
| Auth type | API key (`api-key` header) |
| Post endpoint | `POST /api/articles` |
| Max text length | No practical limit (full articles) |
| Content type | Markdown article (title + body_markdown + tags) |
| Supports images | Yes (via markdown image syntax; images must be hosted externally) |
| Supports links | Yes (markdown links) |
| Rate limits | 30 requests per 30 seconds |
| Cost | Free |
| Feasibility | **No blockers.** Free API key from user settings. Good for cross-posting full blog articles. |
| Notes | `canonical_url` field prevents SEO duplication when cross-posting. |

## LinkedIn

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://api.linkedin.com/rest` |
| Auth type | OAuth2 (3-legged flow) |
| Post endpoint | `POST /rest/posts` |
| Max text length | 3000 characters |
| Supports images | Yes (via `registerUpload` + binary upload) |
| Rate limits | 200 API calls per day per organization |
| Cost | Free API, but requires app review |
| Feasibility | **BLOCKED for org pages** — `w_organization_social` scope requires ~30-day LinkedIn app review. Personal profile posting (`w_member_social`) works immediately. |

### Unblock path

1. Submit OAuth app for LinkedIn review (one-time, ~30 days).
2. Or support personal-profile posting as fast path — no review needed.
3. Browser automation via web-scraper is an alternative that bypasses the API entirely.

## X / Twitter

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://api.twitter.com/2` |
| Auth type | OAuth 1.0a (API key + secret + access token + access secret) |
| Post endpoint | `POST /2/tweets` |
| Max text length | 280 characters |
| Supports images | Yes (via media upload endpoint) |
| Rate limits | 50 tweets per user per 24 hours (Basic tier) |
| Cost | **$200/month** (Basic tier required for write access; Free tier is read-only) |
| Feasibility | **BLOCKED by cost** — write access requires paid Basic tier at $200/month. |

### Unblock path

1. Operator pays for X API Basic tier ($200/month).
2. Or use browser automation via web-scraper to bypass the API.
3. Or deprioritize in favor of free alternatives (Bluesky, Mastodon).

## Reddit

| Property | Value |
|---|---|
| Access method | `api` |
| API base URL | `https://oauth.reddit.com` |
| Auth type | OAuth2 (script or web app type) |
| Post endpoint | `POST /api/submit` |
| Max title length | 300 characters |
| Content type | Link post or self post (markdown) |
| Supports images | Self posts only (host externally) |
| Rate limits | 100 requests per minute per OAuth client |
| Cost | Free |
| Feasibility | **No blockers.** Free API. Subreddit selection is per-tenant config. |
| Notes | Each subreddit has its own posting rules. Agent should record subreddit-specific lessons. |

## Facebook

| Property | Value |
|---|---|
| Access method | `api` or `browser` |
| API base URL | `https://graph.facebook.com/v19.0` |
| Auth type | Page access token (via Facebook Login + page permissions) |
| Post endpoint | `POST /{page-id}/feed` |
| Max text length | 63,206 characters |
| Supports images | Yes |
| Rate limits | 200 calls per hour per page |
| Cost | Free API, but requires Facebook app review for page publishing |
| Feasibility | **Partially blocked** — `pages_manage_posts` permission requires app review. Browser automation is a viable alternative. |

## General notes

- **Browser fallback**: Any platform that blocks API access (cost, review gates) can potentially be accessed via the web-scraper browser tool. Browser hints in the knowledge store guide the agent through the web UI.
- **Knowledge is mutable**: These seeds are starting points. The agent appends lessons as it encounters rate limits, format restrictions, or API changes. Operators can edit knowledge at any time.
- **This document is reference, not config**: The actual knowledge store lives in the `platform_knowledge` DB table. This document informs the seed migration and operator onboarding docs.
