# Astra Agent — Product Requirements Document

## 1. Overview

Astra Agent is an AI-powered content engine for WordPress blog owners. It automates
content creation, publishing, and social media distribution, while also providing an
autonomous Twitter engagement bot.

## 2. Modules

### 2.1 Content Engine (WordPress Integration)

**Goal:** Generate high-quality blog posts from a prompt and publish them to WordPress.

| Requirement | Description | Priority |
|---|---|---|
| CE-1 | Accept a content brief (topic, tone, length, keywords) via CLI or config | P0 |
| CE-2 | Generate blog post (title, body, excerpt, tags, categories) via LLM | P0 |
| CE-3 | Publish draft or live post to WordPress via REST API | P0 |
| CE-4 | Support featured image generation/selection | P1 |
| CE-5 | Batch content generation from a content calendar YAML | P1 |

### 2.2 Social Media Auto-Distribution

**Goal:** When a WordPress post is published, automatically share it to LinkedIn and Twitter.

| Requirement | Description | Priority |
|---|---|---|
| SD-1 | Detect new WordPress post publication (poll or webhook) | P0 |
| SD-2 | Generate platform-specific social copy from post content via LLM | P0 |
| SD-3 | Post to Twitter (tweet with link + summary) | P0 |
| SD-4 | Post to LinkedIn (share with link + summary) | P0 |
| SD-5 | Track which posts have been shared to avoid duplicates | P0 |

### 2.3 Twitter Bot

**Goal:** An autonomous Twitter bot that engages naturally, driven by a system prompt personality.

| Requirement | Description | Priority |
|---|---|---|
| TB-1 | Personality defined via system prompt in config | P0 |
| TB-2 | Search and discover relevant tweets by keyword/hashtag | P0 |
| TB-3 | Reply to tweets with contextual, value-adding responses | P0 |
| TB-4 | Follow relevant accounts | P0 |
| TB-5 | Like tweets as engagement signal | P1 |
| TB-6 | Rate limiting and human-like timing (jitter, delays) | P0 |
| TB-7 | Interaction history tracking (don't re-engage same tweet) | P0 |
| TB-8 | Configurable engagement rules (max replies/day, topics to avoid) | P0 |

### 2.4 Cross-Cutting Concerns

| Requirement | Description | Priority |
|---|---|---|
| CC-1 | YAML-based configuration with env var overrides | P0 |
| CC-2 | SQLite for local state (posts shared, interactions logged) | P0 |
| CC-3 | Structured logging (JSON) | P0 |
| CC-4 | CLI interface for all operations | P0 |
| CC-5 | Pluggable LLM backend (OpenAI, Anthropic) | P1 |
| CC-6 | Dry-run mode for all destructive operations | P0 |
| CC-7 | Comprehensive test suite (unit + integration) | P0 |
| CC-8 | Scheduler for recurring tasks (content generation, bot engagement) | P0 |

## 3. Technical Architecture

```
┌──────────────────────────────────────────────────┐
│                    CLI / Scheduler                │
├──────────────────────────────────────────────────┤
│                  Engine (Orchestrator)            │
├────────────┬────────────┬────────────┬───────────┤
│  LLM       │ WordPress  │  Twitter   │ LinkedIn  │
│  Module    │  Module    │  Module    │ Module    │
├────────────┴────────────┴────────────┴───────────┤
│              Storage (SQLite)                     │
├──────────────────────────────────────────────────┤
│              Config (YAML + Env)                  │
└──────────────────────────────────────────────────┘
```

## 4. Tech Stack

- **Language:** Python 3.11+
- **LLM:** OpenAI SDK (pluggable to Anthropic)
- **WordPress:** REST API via httpx
- **Twitter:** Twitter API v2 via httpx (free tier compatible)
- **LinkedIn:** LinkedIn API via httpx
- **Database:** SQLite via aiosqlite
- **Config:** PyYAML + pydantic-settings
- **CLI:** Click
- **Scheduling:** APScheduler
- **Testing:** pytest + pytest-asyncio
- **HTTP:** httpx (async)

## 5. API Tier Notes

### Twitter Free Tier Limitations
- 1,500 tweets/month (posting only)
- No search, no read access on free tier
- **Recommendation:** Design for Basic tier ($100/mo) which adds read + search.
  Build abstraction layer so free tier does posting-only, basic tier enables full bot.

### LinkedIn
- Requires OAuth 2.0 app with "Share on LinkedIn" product approved
- Community Management API for organization pages

## 6. CTO Review Notes

### Round 1 Feedback
- [ ] Add graceful degradation: if Twitter API fails, queue and retry
- [ ] Add content approval workflow: generate → review → approve → publish
- [ ] The Twitter bot MUST respect rate limits aggressively — account bans are permanent
- [ ] Add a "zero cost" mode for Twitter bot using only free tier (post-only engagement)
- [ ] Ensure all API credentials are validated at startup, not at first use
- [ ] Add health check command to verify all integrations are working

### Round 2 Feedback (incorporated)
- Added CC-6: Dry-run mode — critical for testing without live API calls
- Added TB-6: Human-like timing — essential to avoid bot detection
- Added TB-7: Interaction history — prevents spam behavior
- Clarified Twitter tier strategy in Section 5
- Added content approval workflow as P1 feature

## 7. Delivery Plan

| Version | Scope |
|---|---|
| v1 | Config, LLM, WordPress client, content generation, CLI, storage, tests |
| v2 | Twitter client, LinkedIn client, social distribution, scheduler, tests |
| v3 | Twitter bot (personality, engagement, rate limiting), full integration tests |
