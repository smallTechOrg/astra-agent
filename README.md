# Astra Agent

AI-powered content engine for WordPress blog owners. Generate blog posts with LLMs, auto-distribute to Twitter and LinkedIn, and run an autonomous Twitter engagement bot — all from a single CLI.

## What It Does

**Content Pipeline:** Give it a topic → LLM writes a full blog post → publishes to WordPress → shares on Twitter & LinkedIn with platform-optimized copy.

**Twitter Bot:** Searches for tweets matching your keywords, likes them, follows the authors, and replies with LLM-generated responses that match a configurable personality.

**Daemon Mode:** Run it as a background service with cron-scheduled content generation, social distribution, and engagement — fully hands-off.

## Architecture

```
src/astra/
├── config.py              # YAML + env var configuration (pydantic-settings)
├── cli.py                 # CLI commands: generate, run, engage, health, version
├── core/
│   ├── engine.py          # AstraEngine — main orchestrator, lifecycle manager
│   └── scheduler.py       # Cron-based job scheduler (APScheduler)
├── llm/
│   ├── base.py            # Abstract LLMClient interface
│   ├── openai_client.py   # OpenAI implementation (gpt-4o, etc.)
│   ├── anthropic_client.py# Anthropic implementation (Claude)
│   ├── factory.py         # Provider factory — create_llm_client("openai", ...)
│   └── prompts.py         # All prompt templates (blog, social, bot)
├── wordpress/
│   ├── client.py          # Async WordPress REST API client
│   └── models.py          # WordPressPost, ContentBrief, response models
├── twitter/
│   ├── client.py          # Async Twitter API v2 (OAuth 1.0a writes, Bearer reads)
│   ├── models.py          # Tweet, TwitterUser, SearchResult
│   └── bot.py             # Autonomous engagement bot
├── linkedin/
│   ├── client.py          # Async LinkedIn API client (personal + org pages)
│   └── models.py          # LinkedInShare, LinkedInShareResponse
├── social/
│   └── distributor.py     # Concurrent multi-platform distribution
└── storage/
    ├── database.py        # Async SQLite via aiosqlite
    └── models.py          # PostRecord, InteractionRecord, status enums
```

### How the pieces connect

1. **AstraEngine** is the central orchestrator. It owns the LLM client, WordPress client, social clients (Twitter/LinkedIn), the database, and the `SocialDistributor`.
2. **SocialDistributor** takes a published post's title/excerpt/URL, asks the LLM to generate platform-specific copy, then posts to Twitter and LinkedIn concurrently. Failures on one platform don't block the other.
3. **AstraScheduler** wraps APScheduler and registers three job types: content generation, social distribution (checks DB for unshared posts), and Twitter bot engagement.
4. **TwitterBot** searches for tweets by keyword, checks the DB for prior interactions (idempotent), then likes/follows/replies. Reply text is LLM-generated with a configurable personality.

### Design decisions

- **Fully async** — all I/O uses `httpx.AsyncClient` and `aiosqlite`. The CLI bridges to async via `asyncio.run()`.
- **No external OAuth libraries** — Twitter OAuth 1.0a is implemented with stdlib `hmac`/`hashlib` to keep dependencies minimal.
- **Retry with tenacity** — all external API calls retry on transient errors (connection timeouts, 5xx) with exponential backoff. Rate limits (`429`) raise typed exceptions instead of retrying blindly.
- **Lazy social clients** — Twitter and LinkedIn clients are only instantiated when their credentials are present in config. The engine and distributor handle `None` clients gracefully.
- **Config priority** — Environment variables (`ASTRA_*`) override YAML config, which overrides defaults. This lets you commit a base config and override secrets per-environment.

## Quick Start

### 1. Install

```bash
# Clone and install in editable mode
git clone <repo-url> && cd astra-agent
pip install -e ".[dev]"
```

### 2. Configure

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

> **Note:** Values containing spaces (like WordPress app passwords) must be quoted in `.env`:
> ```bash
> ASTRA_WORDPRESS__APP_PASSWORD="320b fzQS kdNJ VLYL qvl7 GEqV"
> ```

**Required** (minimum to generate posts):
- `ASTRA_LLM__API_KEY` — OpenAI or Anthropic API key
- `ASTRA_WORDPRESS__URL` — your WordPress site URL
- `ASTRA_WORDPRESS__APP_PASSWORD` — WordPress application password ([how to create one](https://make.wordpress.org/core/2020/11/05/application-passwords-integration-guide/))

**Optional** (for social distribution):
- `ASTRA_TWITTER__*` — Twitter API v2 credentials (all 5 fields needed)
- `ASTRA_LINKEDIN__ACCESS_TOKEN` — LinkedIn OAuth2 token (run `astra auth linkedin` to get one)

**For Groq instead of OpenAI/Anthropic:**
- `ASTRA_LLM__PROVIDER=groq`
- `ASTRA_LLM__API_KEY=gsk_...`
- `ASTRA_LLM__MODEL=llama-3.3-70b-versatile`

You can also configure via `config/default.yaml` or a custom YAML file passed with `--config`.

### 3. Get a LinkedIn Access Token (if using LinkedIn)

LinkedIn requires OAuth2. Astra handles the full browser flow for you:

```bash
# One-time setup: add http://localhost:8989/callback as a redirect URL in your
# LinkedIn app at https://www.linkedin.com/developers/apps, then run:
astra auth linkedin --client-id <YOUR_CLIENT_ID> --client-secret <YOUR_SECRET>
```

This opens your browser, you approve access, and the token is printed to paste into `.env`.

**To post as a company/organization page** (instead of your personal profile), also set:
```bash
ASTRA_LINKEDIN__ORGANIZATION_ID=<your_numeric_org_id>
```
Find your org ID in the LinkedIn company admin panel — go to your company page admin URL and look for `organizationUrn` in the page source, or check the URL at `linkedin.com/company/<slug>/admin/`. When `ORGANIZATION_ID` is set, all posts go to the company page automatically.

### 4. Use

```bash
# Generate a blog post (dry run — no publishing)
astra generate --topic "10 Python Testing Best Practices" --dry-run

# Generate and publish as draft
astra generate --topic "Docker for Beginners" --tone casual --word-count 2000

# Generate, publish immediately, with SEO keywords
astra generate --topic "GraphQL vs REST" --publish --keywords "graphql,rest,api"

# Distribute an existing WordPress post to LinkedIn (no generation needed)
astra distribute --post-id 42 --linkedin-only

# Distribute to all configured platforms (Twitter + LinkedIn)
astra distribute --post-id 42

# Check all API connections
astra health

# Run the Twitter engagement bot once
astra engage

# Start daemon mode (scheduled generation + distribution + engagement)
astra run --topic "weekly tech insights"
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `astra generate` | Generate a blog post from a topic. Options: `--topic`, `--tone`, `--word-count`, `--keywords`, `--publish`, `--dry-run`, `--config` |
| `astra distribute` | Distribute an existing WordPress post to social platforms. Options: `--post-id`, `--linkedin-only`, `--twitter-only`, `--config` |
| `astra run` | Start in daemon mode with cron-scheduled jobs. Options: `--topic`, `--tone`, `--word-count`, `--config` |
| `astra engage` | Run the Twitter engagement bot once. Options: `--config` |
| `astra health` | Check WordPress, LLM, database, Twitter, and LinkedIn connectivity |
| `astra auth linkedin` | Get a LinkedIn access token via browser OAuth2 flow. Options: `--client-id`, `--client-secret`, `--port`, `--scope` |
| `astra version` | Print version |

Global flag: `--json-log` switches log output from colored console to JSON (useful for production/log aggregation).

## Configuration

Configuration is loaded in this priority order (highest wins):

1. **Environment variables** — prefixed with `ASTRA_`, nested with `__` (e.g., `ASTRA_LLM__PROVIDER=anthropic`)
2. **YAML config file** — `config/default.yaml` or custom path via `--config`
3. **Field defaults** — sensible defaults for everything

See [config/default.yaml](config/default.yaml) for all available options with comments.

### Key config sections

| Section | What it controls |
|---------|-----------------|
| `llm` | Provider (`openai`/`anthropic`), model, temperature, API key |
| `wordpress` | Site URL, username, application password |
| `twitter` | API keys for read (Bearer) and write (OAuth 1.0a) operations |
| `linkedin` | Access token, optional organization ID |
| `twitter_bot` | Enable/disable, search keywords, max interactions, cooldown |
| `scheduler` | Enable/disable, cron expressions for post/share/engage jobs |
| `database_path` | SQLite file location (default: `data/astra.db`) |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=astra --cov-report=term-missing

# Lint
ruff check src/ tests/

# Type check
mypy src/astra/
```

### Test structure

```
tests/
├── conftest.py              # MockLLMClient, shared fixtures
└── unit/
    ├── test_config.py       # Config loading, YAML, env overrides
    ├── test_storage.py      # Database CRUD, idempotency, schema
    ├── test_llm.py          # Factory, mock client interface
    ├── test_wordpress.py    # WP client with respx HTTP mocking
    ├── test_engine.py       # Engine dry-run + publish with mocked LLM/WP
    ├── test_distributor.py  # Social distributor with mocked clients
    ├── test_twitter.py      # Twitter client with respx HTTP mocking
    └── test_twitter_bot.py  # Bot logic, idempotency, rate limiting
```

89 unit tests, all async, running in ~1 second.

## Project Structure

```
astra-agent/
├── .env.example           # Template for environment variables
├── .gitignore
├── pyproject.toml          # Build config, dependencies, tool settings
├── config/
│   └── default.yaml        # Default configuration with comments
├── src/astra/              # Main package (see Architecture above)
├── tests/                  # Unit tests
└── docs/
    └── requirements.md     # Original requirements document
```

## Requirements

- Python 3.11+
- A WordPress site with REST API enabled and an application password
- At least one LLM API key (OpenAI or Anthropic)
- (Optional) Twitter API v2 credentials for social distribution + bot
- (Optional) LinkedIn API access token for social distribution
