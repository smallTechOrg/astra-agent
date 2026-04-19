# Extensibility

**Status:** DRAFT

Astra grows by adding **knowledge** (data), not adapters (code). The agentic architecture in [`02-architecture.md`](02-architecture.md) means platform interaction is driven by the knowledge store at runtime. The only code-level extension points are sources, tools, and LLM providers.

## Adding a new platform

No code required. A platform is runtime data, not compiled behavior.

1. **Seed knowledge.** Insert a `platform_knowledge` row (see [`07-data-model.md`](07-data-model.md#schema)) with `access_method`, `api_endpoints`, `browser_hints`, `content_constraints`, and initial `lessons`. This is operator work via the UI ([`10-ui-dashboard.md`](10-ui-dashboard.md#knowledge-editor)) or CLI (`astra knowledge`).
2. **Add the platform to a tenant.** `astra platform add --tenant <slug> --platform <name>` creates a `tenant_platforms` row. Provide credentials as secrets (convention: `<PLATFORM>_<KEY>`, stored in the secrets backend per [`05-config.md`](05-config.md#secrets)).
3. **Done.** On the next content event, the agent reads the tenant's platforms, fetches knowledge for each, and distributes using the appropriate tool (HTTP or browser). The agent traces every action.

Example — adding Reddit:
```
# Operator seeds global knowledge (once)
astra knowledge seed reddit --access-method api \
  --api-endpoints '{"base_url": "https://oauth.reddit.com", "submit": "/api/submit"}' \
  --content-constraints '{"max_title_length": 300, "supports_images": true}'

# Tenant enables it
astra platform add --tenant my-blog --platform reddit
# Tenant provides credentials via secrets backend
```

No Python class, no registry entry, no spec file for "Reddit distribution." The agent uses the stored knowledge + generic HTTP tool to post.

### When knowledge is wrong or stale

The agent appends lessons to the knowledge store when things fail (e.g. "API returned 403: need `submit` scope on token"). The operator can also edit knowledge directly via the UI. If a platform's web UI changes and browser hints become stale, the operator updates them — or the agent records the failure and the operator fixes it from the trace log.

## Adding a new source

Sources are the one extension point that requires in-tree code. Each source has a unique polling protocol (WordPress REST API, RSS XML, webhook receiver, etc.) that can't be generalized into a single tool.

1. **Write the spec first.** Add `spec/product/04-capabilities/<name>-publish-detection.md` using the capability template.
2. **Implement the `Source` interface:**
   - `async poll(tenant) -> list[PublishEvent]`
   - `PublishEvent` shape is shared; the new source populates it from its data format.
3. **Register** in the source registry (one line mapping source type string to class).
4. **Update config.** Extend `source.type` enum in [`05-config.md`](05-config.md). Document new fields.
5. **DB:** No schema change — `publish_events.source_name` is free-text.

A tenant sets `source.type: rss` instead of `wordpress`. The downstream agent machinery is unchanged.

## Adding a new tool

Tools are the agent's hands. v1 ships with `http`, `browser`, `knowledge_read`, and `knowledge_write`. Adding a new tool (e.g. `email` for newsletter distribution) is rare and requires code.

1. **Write the spec first.** Describe the tool's interface, trust boundary, and failure modes.
2. **Implement the tool interface** — same contract as existing tools: takes structured input, returns structured output, produces action traces.
3. **Register** in the tool registry so the agent can use it.
4. **Update [`02-architecture.md`](02-architecture.md)** to list the new tool.

## Adding a new LLM provider

Already supported; the `LLMClient` interface exists with multiple implementations.

1. Implement `LLMClient.generate_content()` and `generate_structured()`.
2. Register in the factory.
3. Update `operator_config` provider enum in [`05-config.md`](05-config.md).

No spec capability file needed — LLM choice is an implementation detail.

## Adding a new cadence

A cadence is a scheduled content generation pattern (see [`07-data-model.md`](07-data-model.md#schema)). Adding one is config, not code:

1. Create a `cadence_<name>` prompt in the prompts table (see [`08-prompts.md`](08-prompts.md#cadence_name)).
2. Insert a `cadences` row for the tenant with the name and target platform.
3. The daemon's cadence runner picks it up automatically and uses the prompt + platform knowledge.

## What is explicitly NOT an extension point

- **No plugin loader.** No "point Astra at a directory of arbitrary Python files." Extensions that require code are in-tree with registry entries. This keeps behavior auditable.
- **No webhook DSL or rule engine.** If a tenant needs custom trigger logic, implement it as a proper source.
- **No templating beyond `{var}` in prompts.** If a prompt needs conditional logic, the caller pre-computes a variable.
- **No cross-tenant logic.** A behavior that reads across tenants breaks isolation guarantees in [`03-tenancy.md`](03-tenancy.md).
- **No autonomous knowledge discovery.** In v1 the agent does not browse the internet to learn how to use a new platform from scratch. Operators seed knowledge; the agent refines it.

## The extensibility rule

> **Platforms = knowledge (data). Sources and tools = code (spec-first).** No shortcuts.

The knowledge store is what makes Astra a genuine agent rather than a plugin system. Hardcoding per-platform behavior as Python classes is the thing we explicitly do not do.
