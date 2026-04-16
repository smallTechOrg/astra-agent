# Vision

**Status:** DRAFT

## What Astra is

Astra is a **multi-tenant social distribution agent** for WordPress blogs.

For each tenant it operates on behalf of:
- watches that tenant's WordPress site for newly published posts
- announces those posts on the tenant's LinkedIn organization page and X/Twitter account
- maintains an independent, topic-driven Twitter posting cadence so the feed stays active between blog announcements

One Astra process handles many tenants. Failures on one tenant never affect another.

## What Astra is NOT

Astra does **not**:

- **Write blog content.** WordPress posts are authored by humans in wp-admin. Astra never generates, edits, or publishes to WordPress.
- **Generate images.** No featured-image generation, no inline image generation. The WordPress post already has its own images.
- **Engage on social.** No likes, follows, replies, searches, or mentions monitoring. The paid API tier required to read mentions/search is explicitly out of scope. (See [glossary: engagement](#out-of-scope-engagement).)
- **Post as a personal LinkedIn profile.** Only organization pages. Personal-profile posting was removed because it complicates permissions and muddles audience analytics.
- **Cross-post other sources.** RSS feeds, Mastodon, Threads, Bluesky, Substack, etc. are not supported today. Adding one is a spec-first change per [`09-extensibility.md`](09-extensibility.md).

## Audiences

**Operator** (the person running Astra): wants to onboard a tenant in minutes, trust that distribution keeps running without babysitting, and see clear signals when something breaks.

**Tenant** (the brand whose content is being distributed): never interacts with Astra directly. Experiences Astra only through the posts that appear on their LinkedIn and Twitter on time.

## Success criteria

Astra is working correctly when:

1. A human publishes a blog post in wp-admin → within the tenant's configured poll interval, a LinkedIn post and a tweet appear linking to it.
2. A tenant's configured cadence → tweets appear on schedule, on topic, and don't repeat recent content.
3. One tenant's expired LinkedIn token does not prevent another tenant's distribution.
4. Restarting the daemon mid-run does not cause duplicate posts or lost events.
5. A new tenant can be onboarded end-to-end by writing one YAML file and one `.env` file, no code changes.

## Out of scope: engagement

Reading replies, searching for keywords, liking, following, and replying are explicitly out of scope. The feature requires Twitter's Basic tier ($200/month as of 2025), and workarounds (browser automation, unofficial scrapers, email parsing) either violate ToS or are too fragile to operate for customers. If engagement ever re-enters scope, it lands as a separate capability spec with an explicit paid-tier dependency.
