from __future__ import annotations

from datetime import datetime  # noqa: TC003 — required at runtime by Pydantic

from pydantic import BaseModel, ConfigDict


class TweetMetrics(BaseModel):
    """Public engagement metrics attached to a tweet."""

    model_config = ConfigDict(strict=True, frozen=True)

    retweet_count: int
    reply_count: int
    like_count: int
    impression_count: int


class Tweet(BaseModel):
    """A single tweet returned by the Twitter API v2."""

    model_config = ConfigDict(strict=True, frozen=True)

    id: str
    text: str
    author_id: str
    author_username: str | None = None
    created_at: datetime | None = None
    conversation_id: str | None = None
    public_metrics: TweetMetrics | None = None


class TwitterUser(BaseModel):
    """A Twitter user profile."""

    model_config = ConfigDict(strict=True, frozen=True)

    id: str
    name: str
    username: str
    description: str | None = None
    followers_count: int = 0
    following_count: int = 0


class SearchResult(BaseModel):
    """Paginated search result from the recent-search endpoint."""

    model_config = ConfigDict(strict=True, frozen=True)

    tweets: list[Tweet]
    next_token: str | None = None
