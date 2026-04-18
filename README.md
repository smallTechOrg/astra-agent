# astra-agent

Multi-tenant social distribution agent for WordPress blogs. Watches WordPress sites for new posts and distributes them to LinkedIn organization pages and Twitter/X, while maintaining an independent AI-driven Twitter posting cadence.

One process, many tenants. One tenant failing never affects another.

---

## Requirements

- Python 3.12 (see `.tool-versions`)
- PostgreSQL 14+ (all state lives here — no SQLite, no local files for tenant config)
- A WordPress site with the REST API enabled and an [Application Password](https://make.wordpress.org/core/2020/11/05/application-passwords-integration-guide/) created
- LinkedIn: an organization page + an OAuth 2.0 access token with `w_member_social` scope
- Twitter/X: API v2 credentials (API key, API secret, access token, access secret) with write permission
- An LLM API key (OpenAI, Anthropic, Groq, or Gemini)

---

## Install

```bash
pip install -e ".[dev]"
```

Verify:

```bash
astra --version
```

---

## Quick start

### 1. Create the config directory

```bash
mkdir -p config
```

### 2. Write `config/operator.yaml`

```yaml
llm:
  provider: groq                        # openai | anthropic | groq | gemini
  model: llama-3.3-70b-versatile
  api_key_env: LLM_API_KEY
  max_tokens: 1024
  temperature: 0.8

log_level: info

daemon:
  share_sweep_cron: "*/10 * * * *"
  startup_grace_seconds: 5
```

### 3. Write `config/.env` (gitignored)

```
DATABASE_URL=postgresql://astra:astra@localhost:5432/astra
LLM_API_KEY=your-api-key-here
ASTRA_UI_PASSWORD=your-ui-password        # required if astra ui binds non-loopback
```

### 4. Start PostgreSQL and create the database

```bash
createuser astra --pwprompt        # enter password "astra" (or your choice)
createdb astra -O astra
```

Astra runs migrations automatically on first startup — no manual schema setup needed.

### 5. Add a tenant

```bash
astra tenant add acme-corp --name "Acme Corporation"
```

This creates a row in the `tenants` table with `enabled: false` and an empty `tenant_config` row. All tenant configuration is stored in the PostgreSQL database — there are no per-tenant config files.

Configure the tenant via the **UI wizard** (`astra ui`) or directly via the CLI and DB. See [`spec/product/06-cli.md`](spec/product/06-cli.md) for the full CLI reference.

### 6. Set tenant secrets

```bash
# Secrets are stored in the tenant_secrets table, never on the filesystem.
# Use the UI wizard or set them via the API.
```

### 7. Check health

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

### 8. Run the daemon

```bash
astra run
```

The daemon polls WordPress on the configured cron, distributes new posts to LinkedIn and Twitter, and fires cadence ticks on schedule. Stop with `Ctrl+C`.

### 9. Start the UI (optional)

```bash
astra ui
```

Opens the operator web dashboard at `http://127.0.0.1:8080`. The UI provides tenant onboarding, health monitoring, prompt editing, and manual distribution — all backed by the same PostgreSQL database the daemon uses.

---

## Prompts

Prompts are stored in the `prompts` table in the database — not on the filesystem. Two operator defaults (`linkedin_announcement`, `twitter_announcement`) are seeded by the first migration.

Prompts use `{placeholder}` substitution. An optional `# variables:` header declares expected placeholders; a `---` separator splits system and user parts.

Edit prompts via the UI prompt editor or the API. Tenant-specific overrides take precedence over operator defaults. See [`spec/product/08-prompts.md`](spec/product/08-prompts.md).

---

## LinkedIn OAuth

LinkedIn access tokens require an OAuth 2.0 flow. Astra has a built-in helper:

```bash
astra auth linkedin --tenant acme-corp --client-id <id> --client-secret <secret>
```

This opens a browser URL, starts a local callback server on port 8989, exchanges the code for a token, and writes it to `tenant_secrets` automatically.

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
├── operator.yaml                 # Operator-wide settings
└── .env                          # Gitignored — DATABASE_URL, LLM key, UI password
```

All tenant config, secrets, cadences, and prompts are in the PostgreSQL database. There are no per-tenant filesystem artifacts.

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
astra tenant add <id> [--name "Name"]    # create tenant in DB
astra tenant enable <id>                 # set enabled: true (restart daemon to apply)
astra tenant disable <id>                # set enabled: false
astra tenant remove <id> [--force]       # delete all DB rows for this tenant
```

---

## Spec and engineering docs

| Topic | File |
|---|---|
| Product vision | [`spec/product/01-vision.md`](spec/product/01-vision.md) |
| Architecture | [`spec/product/02-architecture.md`](spec/product/02-architecture.md) |
| Tenancy model | [`spec/product/03-tenancy.md`](spec/product/03-tenancy.md) |
| Configuration reference | [`spec/product/05-config.md`](spec/product/05-config.md) |
| Full CLI reference | [`spec/product/06-cli.md`](spec/product/06-cli.md) |
| Data model (PostgreSQL) | [`spec/product/07-data-model.md`](spec/product/07-data-model.md) |
| Prompts | [`spec/product/08-prompts.md`](spec/product/08-prompts.md) |
| UI dashboard | [`spec/product/10-ui-dashboard.md`](spec/product/10-ui-dashboard.md) |
| Capabilities | [`spec/product/04-capabilities/`](spec/product/04-capabilities/) |
| Engineering rules | [`spec/engineering/`](spec/engineering/) |
