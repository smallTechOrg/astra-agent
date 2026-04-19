# Vision

**Status:** DRAFT

## What Astra is

Astra is a **multi-tenant intelligent content distribution agent**. It takes content from any configured source, reasons about where and how to distribute it, and posts to any platform — using APIs or browser automation — with every single action traced and debuggable.

Astra is an **agent**, not a plugin system. There are no hardcoded per-platform adapters. Instead:
- The agent has **tools** (HTTP client, browser automation via external `web-scraper`, knowledge store)
- **Platform knowledge is runtime data**, not compiled code — the agent reads it, follows it, and updates it when things change
- When a platform's UI changes or an API breaks, the agent adapts — it doesn't require a code deploy
- Every action the agent takes — every LLM call, every API request, every browser click — is recorded as an **action trace** visible in the UI

For each tenant it operates on behalf of:
- detects new content from configured sources (WordPress sites, media uploads, API triggers)
- builds a **distribution plan**: the agent reasons about the content, the tenant's platforms, and each platform's known conventions to decide where to post and what copy to generate
- executes the plan using tools — calling APIs directly or driving a browser via the external `web-scraper`
- records a full **action trace** for every step: reasoning, tool invocations, inputs, outputs, errors
- optionally holds the plan for human approval before execution

One Astra process handles many tenants. Failures on one tenant never affect another.

## What Astra is NOT

Astra does **not**:

- **Write source content.** Blog posts are authored by humans. Media is uploaded by humans. Astra never generates, edits, or publishes _source_ content — it only distributes it.
- **Generate images.** No image generation. Source content supplies its own images; Astra attaches them to platform posts where supported.
- **Engage on social.** No likes, follows, replies, searches, or mentions monitoring. Engagement is a fundamentally different product concern and is out of scope.
- **Own platform accounts.** Astra posts on behalf of tenants using their credentials. It has no accounts of its own.
- **Hardcode platform integrations.** No `BlueskyDestination` class, no `MastodonAdapter`. Platform interaction logic lives in the knowledge store as runtime data, executed by the agent via generic tools.

## Design principles

1. **Agent, not adapters.** Platform knowledge is data, not code. The agent reads from a knowledge store, uses generic tools (HTTP, browser), and updates knowledge when it learns something new. Adding a new platform is a configuration + knowledge task, not a development task.
2. **Every action is traceable.** Every LLM call, every API request, every browser navigation, every decision the agent makes — all recorded with inputs, outputs, timing, and reasoning. The operator can drill into any distribution and see exactly what happened and why.
3. **Every action is debuggable.** When something fails, the trace shows the exact step, the exact error, and the context the agent had at the time. No "it just didn't work."
4. **Free and cheap first.** Prefer platforms with free API write access. Platforms behind paid tiers (e.g. X/Twitter at $200/mo) are reachable via browser automation but documented as fragile. The operator decides which platforms are worth running.
5. **Adaptive execution.** If a platform's API changes or its UI is redesigned, the agent detects the failure, logs it, and the knowledge store can be updated — without a code release.
6. **Observable everything.** Distribution plans, agent reasoning, per-platform status, and full action traces are all visible in the UI. No black boxes.

## Content types (v1)

| Type | Fields | Source |
|---|---|---|
| **Blog post** | title, body, URL, excerpt, featured image | WordPress polling |
| **Media** | image(s), description/caption | API trigger / future: media upload |

The architecture supports arbitrary content types. V1 implements these two. Adding a content type is a spec-first change per [`09-extensibility.md`](09-extensibility.md).

## Audiences

**Operator** (the person running Astra): wants to onboard a tenant in minutes, add platforms by providing credentials and optionally seeding knowledge, trust that distribution runs without babysitting, see the full trace of every agent action, and debug failures without reading source code.

**Tenant** (the brand whose content is being distributed): never interacts with Astra directly. Experiences Astra through content appearing on their platforms on time. Depending on tenant config, may review an approval queue before posts go live.

## Success criteria

Astra is working correctly when:

1. A human publishes content → within the configured poll interval, the agent generates a distribution plan selecting appropriate platforms and generating platform-specific copy.
2. The plan executes across all selected platforms. Each platform's result is independently tracked.
3. The operator can see the full action trace for any distribution: every LLM call, every API request, every browser action, every decision — with inputs, outputs, and timing.
4. When a platform API changes or a browser flow breaks, the failure shows up in the trace with enough context to update the knowledge store — no code changes required.
5. One tenant's failure does not affect another tenant. One platform's failure does not block other platforms.
6. Restarting the daemon mid-run does not cause duplicate posts or lost events.
7. A new tenant can be onboarded via the UI wizard or CLI. A new platform can be added by providing credentials and (optionally) seeding the knowledge store with API/browser instructions.
8. When approval mode is enabled, plans are held until explicitly approved, edited, or rejected via the UI.

## Out of scope

- **Social engagement** (likes, follows, replies, mentions). Different product concern, different API tier requirements.
- **Content generation from scratch.** Astra distributes existing content; it does not create original content.
- **Cross-tenant logic.** A capability that reads across tenants breaks isolation guarantees in [`03-tenancy.md`](03-tenancy.md).
- **Platform account management.** Creating accounts, managing followers, analytics. Astra posts content; platform analytics are the platform's job.
- **Autonomous knowledge discovery.** V1 does not browse the internet to learn a new platform from scratch. The operator seeds knowledge (or Astra ships with seed knowledge for common platforms). Autonomous discovery is a future capability.
