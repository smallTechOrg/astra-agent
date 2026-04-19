# Prompts

**Status:** DRAFT

Prompts are first-class spec artifacts, not source code constants. They live in the PostgreSQL database (`prompts` table) and are loaded at runtime. This lets the operator tune tone without code deploys via the UI, and lets each tenant override for brand voice.

## Storage

Prompts are rows in the `prompts` table (see [`07-data-model.md`](07-data-model.md#schema)). Each row has an optional `tenant_id`: rows with `tenant_id IS NULL` are operator-level defaults; rows with a `tenant_id` are tenant-specific overrides.

The UI ([`10-ui-dashboard.md`](10-ui-dashboard.md#prompt-editor)) and CLI are the write paths. The daemon reads prompts from the DB.

## Seeding

On first migration, Astra inserts the required operator-level defaults from bundled seed content in the migration. These can be edited via the UI afterward. If the rows already exist, the migration is a no-op (idempotent).

Required seed prompts:
- `distribution_planner` — the agent's core reasoning prompt for deciding where and how to distribute content
- `platform_copy` — the generic prompt for generating platform-specific copy

## Resolution order

For prompt `{name}` when running tenant `<id>`:

1. `prompts` row where `tenant_id = <id>` and `name = <name>` — tenant override
2. `prompts` row where `tenant_id IS NULL` and `name = <name>` — operator default

If neither exists, **the daemon fails to start** for this tenant with a clear error. No implicit fallback, no silent use-the-old-prompt.

## Prompt content format

Prompts are plain text with Python-style `{placeholder}` substitution. The first line of the content *may* be a machine-readable header comment declaring variables:

```
# variables: title, excerpt, url
```

If present, the loader validates that all declared variables are passed at render time and no undeclared ones are used. This catches typos like `{titile}`.

Rest of the content is the prompt, possibly including a `---` separator between system and user parts:

```
# variables: content_type, title, body, url, platforms_json
You are an intelligent content distribution agent...
---
Analyze this content and generate distribution copy for each platform:
Content type: {content_type}
Title: {title}
Body: {body}
URL: {url}
Target platforms: {platforms_json}
```

When the `---` separator is present, content above becomes the LLM `system_prompt` and content below becomes the `user_prompt`. When absent, the whole content is the user prompt and system is null.

## Prompt contracts

Each prompt is a contract between the spec and the code. Changing the variable list is a breaking change requiring a spec update.

### `distribution_planner`

**Variables:** `{content_type}`, `{title}`, `{body}`, `{url}`, `{excerpt}`, `{images_json}`, `{platforms_json}`, `{tenant_name}`

**Called by:** The agent's planning phase for every new content event.

**`{platforms_json}`** is a JSON array of the tenant's enabled platforms with their knowledge:
```json
[
  {"platform": "bluesky", "max_text_length": 300, "supports_images": true, "lessons": ["..."]},
  {"platform": "mastodon", "max_text_length": 500, "supports_images": true, "lessons": ["..."]},
  {"platform": "devto", "max_text_length": null, "supports_images": true, "content_type": "article", "lessons": ["..."]}
]
```

**Expected output:** Structured JSON with one entry per platform:
```json
{
  "items": [
    {"platform": "bluesky", "action": "post", "reasoning": "...", "copy": "..."},
    {"platform": "devto", "action": "skip", "reasoning": "Content is a photo gallery; DEV.to only supports articles."}
  ]
}
```

The agent uses `LLMClient.generate_structured()` to parse the response. Invalid JSON causes a traced error and plan failure.

### `platform_copy`

**Variables:** `{content_type}`, `{title}`, `{body}`, `{url}`, `{excerpt}`, `{platform}`, `{content_constraints_json}`, `{tenant_name}`

**Called by:** The agent when generating copy for a single platform (if the planner delegates per-platform copy generation to a separate LLM call rather than doing it all at once).

**Expected output:** Platform-appropriate text. Length and format constraints are provided in `{content_constraints_json}` and the LLM must respect them.

**Must not contain:** Irrelevant hashtag spam, `@` mentions that don't resolve, JSON (this prompt returns raw text, not structured output).

### `cadence_<name>`

**Variables:** `{recent_posts}`, `{platform}`, `{content_constraints_json}`, `{tenant_name}`

**Called by:** Cadence runner for the corresponding cadence name.

**Expected output:** A single post for the cadence's configured platform, respecting the platform's content constraints.

**`{recent_posts}`** is a newline-separated list of recent posts from this cadence:
```
Recent posts from this cadence (do not repeat these themes or phrasings):
- Post one text here
- Post two text here
...
```

When there are no recent posts, `{recent_posts}` is rendered as `(none yet — this is the first post in this cadence)`.

**Authoring guidance (non-contractual):** cadence prompts are where the topic/voice live. They're the operator's most important tuning surface. Common patterns:

- A daily-quote prompt references a subject domain and asks for a short aphorism.
- A daily-tip prompt asks for one actionable insight in a specific area.
- A "what I'm reading" prompt asks for a recommendation with a brief reason.

The prompt author is responsible for steering away from repetition beyond what `{recent_posts}` can enforce.

## Operator-default prompts

These **must** exist in the `prompts` table (with `tenant_id IS NULL`) for Astra to start at all:

- `distribution_planner`
- `platform_copy`

Cadence prompts are named by cadence — no universal default required, but every configured cadence must have either an operator default or a per-tenant override in the `prompts` table. Absence at startup is a fatal error for that tenant.

## Versioning prompts

Prompts are DB rows, not files. There is no git history for prompt changes in v1. The `updated_at` column records the last edit timestamp. A future version may add a `prompts_history` audit table.

Changing a prompt's **variables** is a breaking change — the spec section above must be updated in the same commit as any code change. Changing a prompt's **wording** is a routine edit via the UI, no spec change needed.

## Testing prompts

`astra distribute --tenant <id> --source-content-id <id> --dry-run` (future) would render the LLM output to stdout without posting. **Not in v1.** Until then, prompt testing means running the real pipeline with `approval_mode = true` and reviewing the plan in the UI before approving.
