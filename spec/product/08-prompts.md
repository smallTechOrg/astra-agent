# Prompts

**Status:** DRAFT

Prompts are first-class spec artifacts, not source code constants. They live in the PostgreSQL database (`prompts` table) and are loaded at runtime. This lets the operator tune tone without code deploys via the UI, and lets each tenant override for brand voice.

## Storage

Prompts are rows in the `prompts` table (see [`07-data-model.md`](07-data-model.md#schema)). Each row has an optional `tenant_id`: rows with `tenant_id IS NULL` are operator-level defaults; rows with a `tenant_id` are tenant-specific overrides.

The UI ([`10-ui-dashboard.md`](10-ui-dashboard.md#prompt-editor)) and CLI are the write paths. The daemon reads prompts from the DB.

## Seeding

On first migration, Astra inserts the two required operator-level defaults (`linkedin_announcement`, `twitter_announcement`) from bundled seed content in the migration. These can be edited via the UI afterward. If the rows already exist, the migration is a no-op (idempotent).

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
# variables: title, excerpt, url
You are a social media editor for a Buddhist philosophy publication...
---
Write a LinkedIn post about this blog article:
Title: {title}
Excerpt: {excerpt}
URL: {url}
```

When the `---` separator is present, content above becomes the LLM `system_prompt` and content below becomes the `user_prompt`. When absent, the whole content is the user prompt and system is null.

## Prompt contracts

Each prompt is a contract between the spec and the code. Changing the variable list is a breaking change requiring a spec update.

### `linkedin_announcement`

**Variables:** `{title}`, `{excerpt}`, `{url}`, `{tenant_name}`

**Called by:** LinkedIn distribution capability.

**Expected output:** 700–3000 characters. Plain text, no markdown. Tone appropriate for LinkedIn org page (professional, substantive, not salesy). URL must appear in the output text (LinkedIn also renders a preview card from the article block, but the URL in the body gives the human reader something to click).

**Must not contain:** `#` hashtag spam (0–3 tasteful hashtags OK), `@` mentions that don't resolve, JSON, code fences.

### `twitter_announcement`

**Variables:** `{title}`, `{excerpt}`, `{url}`, `{tenant_name}`

**Called by:** Twitter blog-announcement capability.

**Expected output:** ≤ 260 characters (leaving room for URL expansion). URL must be the last token or appear inline. Plain text, no markdown.

**Must not contain:** Quotes wrapping the entire output, leading/trailing whitespace (stripped anyway), emoji-only content.

### `twitter_cadence_<name>`

**Variables:** `{recent_tweets}`, `{tenant_name}`

**Called by:** Twitter scheduled-cadence capability, one prompt per cadence `name`.

**Expected output:** Single tweet, 20–280 characters. No URL unless the prompt explicitly wants one (e.g. a prompt that references the blog homepage).

**`{recent_tweets}`** is a newline-separated list of the tenant's last N cadence tweets for this cadence_name, where the system inserts a header like:

```
Recent tweets from this cadence (do not repeat these themes or phrasings):
- Tweet one text here
- Tweet two text here
...
```

When there are no recent tweets, `{recent_tweets}` is rendered as `(none yet — this is the first tweet in this cadence)`.

**Authoring guidance (non-contractual):** cadence prompts are where the topic/voice live. They're the operator's most important tuning surface. Common patterns:

- A daily-quote prompt references a subject domain and asks for a short aphorism.
- A daily-tip prompt asks for one actionable insight in a specific area.
- A "what I'm reading" prompt asks for a recommendation with a brief reason.

The prompt author is responsible for steering away from repetition beyond what `{recent_tweets}` can enforce.

## Operator-default prompts

These **must** exist in the `prompts` table (with `tenant_id IS NULL`) for Astra to start at all, even if no tenant uses them:

- `linkedin_announcement`
- `twitter_announcement`

These are seeded by the initial migration. If they are accidentally deleted, they can be re-created via the UI or by re-running the migration seed (which is idempotent — inserts only if absent).

Cadence prompts are named by cadence — no universal default required, but every configured cadence must have either an operator default or a per-tenant override in the `prompts` table. Absence at startup is a fatal error for that tenant.

## Versioning prompts

Prompts are DB rows, not files. There is no git history for prompt changes in v1. The `updated_at` column records the last edit timestamp. A future version may add a `prompts_history` audit table.

Changing a prompt's **variables** is a breaking change — the spec section above must be updated in the same commit as any code change. Changing a prompt's **wording** is a routine edit via the UI, no spec change needed.

## Testing prompts

`astra distribute --tenant <id> --wp-post-id <id> --dry-run` (future: currently `--force` + manual check) would render the LLM output to stdout without posting. **Not in v1.** Until then, prompt testing means running the real pipeline in a throwaway tenant.
