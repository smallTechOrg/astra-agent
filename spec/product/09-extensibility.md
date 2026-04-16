# Extensibility

**Status:** DRAFT

Astra is designed to grow. The four abstractions in [`02-architecture.md`](02-architecture.md) — `Source`, `Destination`, `Cadence`, `LLMClient` — are the extension points. Adding anything else requires a spec update first.

## Adding a new destination (example: Mastodon)

1. **Write the spec first.** Add `spec/04-capabilities/mastodon-distribution.md` using the capability template. Decide: auth model, rate limits, output format, failure modes, out-of-scope items.
2. **Extend the config schema.** In [`05-config.md`](05-config.md), add a `destinations.mastodon` block with its keys (`instance_url`, `access_token_env`, `prompt`, `enabled`). Add example to the tenant.yaml sample.
3. **Implement the `Destination` interface.** One class, one module. Same contract as `LinkedInOrgDestination`:
   - `async publish(tenant, event, copy) -> PublishResult`
   - `async health_check(tenant) -> HealthStatus`
4. **Register.** A single line in the destination registry maps the platform string (`"mastodon"`) to the class.
5. **Add the default prompt.** `prompts/mastodon_announcement.txt`.
6. **DB schema.** Usually no change — `distribution_records.platform` is a free-text column. If the platform needs additional state (e.g. a second token type), add a new `destination_state` column in a migration.
7. **CLI.** `astra distribute --platform mastodon` and `astra health` pick it up automatically via the registry.

No changes to `WordPressSource`, the scheduler, or any other tenant's code.

## Adding a new source (example: RSS)

1. Spec: `spec/04-capabilities/rss-publish-detection.md`. Same template.
2. Config: extend `source.type` enum in [`05-config.md`](05-config.md). Document new fields (`feed_url`, etc.).
3. Implement the `Source` interface:
   - `async poll(tenant) -> list[PublishEvent]`
   - `PublishEvent` shape is shared; RSS just populates it from feed entries.
4. Register in the source registry.
5. DB: no change; `publish_events.source_name` is free-text.

A tenant can now set `source.type: rss` instead of `wordpress`. The downstream distribution machinery is unchanged.

## Adding a new cadence type (example: LinkedIn cadence)

v1 only has `TwitterCadence`. A LinkedIn-native cadence (periodic thought-leadership posts to the org page, independent of blog) would be:

1. Spec: `spec/04-capabilities/linkedin-scheduled-cadence.md`.
2. Config: a new top-level `cadences` entry supporting `platform: linkedin`, or split into `twitter_cadences:` and `linkedin_cadences:`. Decision deferred to when this capability is specced.
3. Implement a new `Cadence` implementation.
4. Register. The daemon picks up the new cadence type the same way it picks up `TwitterCadence`.

## Adding a new LLM provider

This is already supported; the `LLMClient` interface exists and has four concrete implementations. To add a fifth:

1. Implement `LLMClient.generate_content()` and `generate_structured()`.
2. Register in the factory.
3. Update `operator.yaml` provider enum in [`05-config.md`](05-config.md).

No spec capability file needed — LLM choice is an implementation detail, not a user-visible capability.

## What is explicitly NOT an extension point

Do not add new plug-in mechanisms without a spec change. Specifically:

- **No plugin loader.** No "point Astra at a directory of arbitrary Python files and it loads them." Extensions are in-tree code with registry entries. This keeps behavior auditable.
- **No webhook DSL.** If a tenant wants a webhook from their WP site, we either poll faster or write a `WordPressWebhookSource` as a full in-tree implementation. Not a configurable rule engine.
- **No templating layer beyond `{var}` in prompts.** If a prompt needs logic (e.g. conditional sections), the prompt author restructures the prompt or we add a variable that's pre-computed in code.
- **No cross-tenant logic.** A capability that reads across tenants (e.g. "post to tenant B's account when tenant A publishes") is not supported and is not a v2 extension — it breaks the isolation guarantees in [`03-tenancy.md`](03-tenancy.md).

## The extensibility rule

> Every new behavior goes through: spec file → config schema → interface implementation → registry entry. No shortcuts.

The registry pattern (platform string → class) is what keeps the daemon agnostic. The capability template is what keeps behavior auditable. Skipping either breaks spec-driven development.
