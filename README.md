# astra-agent

Multi-tenant social distribution agent for WordPress blogs. Watches WordPress sites for new posts and distributes them to LinkedIn organization pages and Twitter/X, while maintaining an independent AI-driven Twitter posting cadence.

One process, many tenants. One tenant failing never affects another.

---

## Requirements

- Python 3.12 (see `.tool-versions`)
- PostgreSQL 14+ (all state lives here)
- Node.js 20+ (only needed for UI development — operators don't need it)
- An LLM API key (OpenAI, Anthropic, Groq, or Gemini)

---

## Quick start

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Create `config/.env`

```bash
mkdir -p config
cat > config/.env <<'EOF'
DATABASE_URL=postgresql://astra:astra@localhost:5432/astra
EOF
```

### 3. Start PostgreSQL and create the database

```bash
createuser astra --pwprompt
createdb astra -O astra
```

### 4. Build and start the UI

```bash
cd ui && npm install && npm run build && cd ..
astra ui --open
```

Opens `http://127.0.0.1:8080`. Everything — operator config, secrets, tenants, cadences, prompts — is managed from the browser. No CLI required for normal operation.

### 5. Start the daemon

```bash
astra run
```

Watches WordPress, distributes posts, runs cadences. Stop with `Ctrl+C`.

---

## UI development

The frontend is a Next.js 15 app in `ui/` with Turbopack HMR.

```bash
# Terminal 1: Python API backend
astra ui

# Terminal 2: Next.js dev server (hot reload)
cd ui && npm install && npm run dev
```

Open `http://localhost:3000` — the Next.js dev server proxies `/api/*` to `http://127.0.0.1:8080`.

To build for production (output goes to `src/astra/ui/out/`):

```bash
cd ui && npm run build
```

---

## CLI reference

The CLI mirrors everything the UI does. Power users can use it directly.

```bash
astra config show                        # show operator config
astra config set llm_provider groq       # set a config value
astra tenant list                        # list tenants
astra tenant add acme-corp --name "Acme" # create a tenant
astra tenant enable acme-corp            # enable a tenant
astra tenant disable acme-corp
astra tenant remove acme-corp --force
astra health                             # check connectivity
astra distribute --tenant acme-corp --wp-post-id 123
astra cadence run --tenant acme-corp --name daily-tips
astra events --tenant acme-corp
astra tweets --tenant acme-corp
astra auth linkedin --tenant acme-corp --client-id <id> --client-secret <secret>
```

---

## Prompts

Prompts live in the database `prompts` table. Two defaults (`linkedin_announcement`, `twitter_announcement`) are seeded on first migration. Edit them from the UI prompt editor. Tenant overrides take precedence over operator defaults. See [`spec/product/08-prompts.md`](spec/product/08-prompts.md).

---

## Config file layout

```
config/
└── .env          # DATABASE_URL (required), ASTRA_UI_PASSWORD (optional)
```

Everything else is in the database — operator config, secrets, tenant config, tenant secrets, cadences, and prompts.

---

## LLM providers

| Provider | Model examples |
|---|---|
| `openai` | `gpt-4o-mini`, `gpt-4o` |
| `anthropic` | `claude-haiku-4-5-20251001`, `claude-sonnet-4-6` |
| `groq` | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` |
| `gemini` | `gemini-1.5-flash`, `gemini-1.5-pro` |

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
