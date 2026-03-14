from __future__ import annotations

from astra.llm.base import LLMClient
from astra.llm.factory import create_llm_client
from astra.llm.prompts import (
    BLOG_POST_SYSTEM_PROMPT,
    BLOG_POST_USER_PROMPT,
    SOCIAL_LINKEDIN_PROMPT,
    SOCIAL_TWEET_PROMPT,
    TWITTER_BOT_REPLY_PROMPT,
)

__all__ = [
    "BLOG_POST_SYSTEM_PROMPT",
    "BLOG_POST_USER_PROMPT",
    "LLMClient",
    "SOCIAL_LINKEDIN_PROMPT",
    "SOCIAL_TWEET_PROMPT",
    "TWITTER_BOT_REPLY_PROMPT",
    "create_llm_client",
]
