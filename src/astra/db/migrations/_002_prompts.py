"""Migration 002: prompts table + operator-default seed data.

Adds the prompts table (IF NOT EXISTS for DBs that already ran an updated 001)
and seeds the two required operator-default prompts per spec/product/08-prompts.md.
"""

from __future__ import annotations

SQL = """
-- Create prompts table if it doesn't already exist (updated 001 includes it).
CREATE TABLE IF NOT EXISTS prompts (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prompts_operator_default
    ON prompts (name) WHERE tenant_id IS NULL;

-- Seed operator-default prompts. ON CONFLICT = idempotent.
INSERT INTO prompts (tenant_id, name, content) VALUES
(NULL, 'linkedin_announcement', '# variables: title, excerpt, url, tenant_name
You are a social media editor for {tenant_name}. Write a professional LinkedIn post announcing a new blog article to the organization''s followers. Plain text only, no markdown. 700-3000 characters. Include the URL as a clickable link on its own line. Zero to three tasteful hashtags maximum.
---
Announce this newly-published blog post to the {tenant_name} LinkedIn audience:

Title: {title}
Excerpt: {excerpt}
URL: {url}'),
(NULL, 'twitter_announcement', '# variables: title, excerpt, url, tenant_name
You are a social media editor for {tenant_name}. Write a single tweet announcing a new blog post. Plain text, no markdown. No wrapping quotes. 260 characters or fewer for the body. The URL {url} must appear in the tweet.
---
Announce this blog post in one tweet:

Title: {title}
Excerpt: {excerpt}
URL: {url}')
ON CONFLICT DO NOTHING;
"""
