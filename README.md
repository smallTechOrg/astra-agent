# astra-agent

Multi-tenant social distribution agent for WordPress blogs. Watches WordPress sites for new posts and distributes them to LinkedIn organization pages and Twitter/X, while maintaining an independent AI-driven Twitter posting cadence.

One process, many tenants. One tenant failing never affects another.

---

## Requirements

- Python 3.12 (see `.tool-versions`)
- A WordPress site with the REST API enabled and an [Application Password](https://make.wordpress.org/core/2020/11/05/application-passwords-integration-guide/) created
- LinkedIn: an organization page + an OAuth 2.0 access token with `w_member_social` scope
- Twitter/X: API v2 credentials (API key, API secret, access token, access secret) with write permission
- An LLM API key (OpenAI, Anthropic, Groq, or Gemini)

---

## Install

```bash
pip install -e .
```

Verify:

```bash
astra --version
```

---

## Quick start

### 1. Create the config directory

```bash
mkdir -p config prompts
```

### 2. Write `config/operator.yaml`

```yaml
llm:
  provider: groq                        # openai | anthropic | groq | gemini
  model: llama-3.3-70b-versatile
  api_key_env: LLM_API_KEY
  max_tokens: 1024
  temperature: 0.8

database_path: state/astra.db
log_level: info
```

### 3. Write `config/.env` (gitignored)

```
LLM_API_KEY=your-api-key-here
```

### 4. Add a tenant

```bash
astra tenant add acme-corp --name "Acme Corporation"
```

This creates `config/tenants/acme-corp/tenant.yaml` (with `enabled: false`) and an empty `.env`.

Edit `config/tenants/acme-corp/tenant.yaml`:

```yaml
id: acme-corp
name: "Acme Corporation"
enabled: true

source:
  type: wordpress
  url: "https://blog.acme.com"
  username: "admin"
  app_password_env: WP_APP_PASSWORD
  poll_cron: "*/5 * * * *"

destinations:
  linkedin:
    enabled: true
    organization_id: "12345678"
    access_token_env: LINKEDIN_ACCESS_TOKEN
    prompt: linkedin_announcement

  twitter:
    enabled: true
    api_key_env: TWITTER_API_KEY
    api_secret_env: TWITTER_API_SECRET
    access_token_env: TWITTER_ACCESS_TOKEN
    access_secret_env: TWITTER_ACCESS_SECRET
    announcement_prompt: twitter_announcement

cadences:
  - name: daily-tips
    cron: "0 14 * * *"
    prompt: twitter_cadence_daily_tips
    feedback_last_n: 20
    enabled: true
```

Edit `config/tenants/acme-corp/.env`:

```
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
LINKEDIN_ACCESS_TOKEN=AQUz...
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
```

### 5. Write prompt files

Astra looks in `prompts/` for operator-wide defaults, and in `config/tenants/<id>/prompts/` for per-tenant overrides.

`prompts/linkedin_announcement.txt`:
```
Write a LinkedIn post for a {{tenant_name}} blog article.

Title: {{title}}
URL: {{url}}
Excerpt: {{excerpt}}

Keep it under 250 words. Professional tone. End with the article URL.
```

`prompts/twitter_announcement.txt`:
```
Write a tweet announcing a new {{tenant_name}} blog post.

Title: {{title}}
URL: {{url}}

Under 280 characters including the URL. Engaging and concise.
```

`prompts/twitter_cadence_daily-tips.txt`:
```
Write a standalone tip tweet for {{tenant_name}}.

Recent tweets (avoid repeating): {{recent_tweets}}

Topic: share a practical tip relevant to the brand. Under 280 characters.
```

Available template variables: `{{tenant_name}}`, `{{title}}`, `{{url}}`, `{{excerpt}}`, `{{recent_tweets}}`.

### 6. Check health

```bash
astra health
```

Expected output:
```
Operator
  Database:       ok
  LLM (groq):     ok (key present, not tested)

Tenant: acme-corp
  WordPress:      ok
  LinkedIn:       ok
  Twitter:        ok
```

Fix any `FAILED` lines before proceeding.

### 7. Run the daemon

```bash
astra run
```

The daemon polls WordPress on the configured cron, distributes new posts to LinkedIn and Twitter, and fires cadence ticks on schedule. Stop with `Ctrl+C`.

---

## LinkedIn OAuth

LinkedIn access tokens require an OAuth 2.0 flow. Astra has a built-in helper:

```bash
astra auth linkedin --tenant acme-corp --client-id <id> --client-secret <secret>
```

This opens a browser URL, starts a local callback server on port 8989, exchanges the code for a token, and writes it to the tenant's `.env` automatically.

---

## Manual commands

**Re-distribute a specific WordPress post:**

```bash
astra distribute --tenant acme-corp --wp-post-id 123
astra distribute --tenant acme-corp --wp-post-id 123 --platform linkedin   # one platform only
astra distribute --tenant acme-corp --wp-post-id 123 --force               # re-send even if already sent
```

**Fire one cadence tick immediately:**

```bash
astra cadence run --tenant acme-corp --name daily-tips
```

**Inspect recent events and their distribution status:**

```bash
astra events --tenant acme-corp
astra events --tenant acme-corp --limit 50
```

**Inspect cadence tweet history:**

```bash
astra tweets --tenant acme-corp
astra tweets --tenant acme-corp --cadence daily-tips
```

---

## Config file layout

```
config/
├── operator.yaml
├── .env                          # gitignored — LLM key, etc.
└── tenants/
    └── <tenant-id>/
        ├── tenant.yaml
        ├── .env                  # gitignored — per-tenant secrets
        └── prompts/              # optional per-tenant prompt overrides

prompts/                          # operator-wide prompt defaults
state/
└── astra.db                      # SQLite — created on first run
```

---

## Supported LLM providers

| `provider` value | Model examples |
|---|---|
| `openai` | `gpt-4o-mini`, `gpt-4o` |
| `anthropic` | `claude-haiku-4-5-20251001`, `claude-sonnet-4-6` |
| `groq` | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` |
| `gemini` | `gemini-1.5-flash`, `gemini-1.5-pro` |

---

## Tenant management

```bash
astra tenant list                        # show all tenants with status
astra tenant add <id> [--name "Name"]    # scaffold new tenant
astra tenant enable <id>                 # set enabled: true (restart daemon to apply)
astra tenant disable <id>                # set enabled: false
astra tenant remove <id> [--force]       # delete config dir + all DB rows
```

---

## Spec and engineering docs

| Topic | File |
|---|---|
| Product vision | [`spec/product/01-vision.md`](spec/product/01-vision.md) |
| Configuration reference | [`spec/product/05-config.md`](spec/product/05-config.md) |
| Full CLI reference | [`spec/product/06-cli.md`](spec/product/06-cli.md) |
| Capabilities | [`spec/product/04-capabilities/`](spec/product/04-capabilities/) |
| Engineering rules | [`spec/engineering/`](spec/engineering/) |
