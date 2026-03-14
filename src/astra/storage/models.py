from __future__ import annotations

import enum
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PostStatus(enum.StrEnum):
    """Lifecycle status of a blog post."""

    DRAFT = "draft"
    PUBLISHED = "published"
    FAILED = "failed"


class ShareStatus(enum.StrEnum):
    """Whether a post has been shared on a given platform."""

    PENDING = "pending"
    SHARED = "shared"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionType(enum.StrEnum):
    """Type of Twitter interaction the bot performed."""

    LIKE = "like"
    RETWEET = "retweet"
    REPLY = "reply"
    FOLLOW = "follow"


class PostRecord(BaseModel):
    """Represents a row in the *posts* table."""

    model_config = ConfigDict(strict=True, frozen=True)

    id: int
    wp_post_id: int | None = None
    title: str
    status: PostStatus = PostStatus.DRAFT
    shared_twitter: ShareStatus = ShareStatus.PENDING
    shared_linkedin: ShareStatus = ShareStatus.PENDING
    created_at: datetime = Field(default_factory=_utcnow)


class InteractionRecord(BaseModel):
    """Represents a row in the *interactions* table."""

    model_config = ConfigDict(strict=True, frozen=True)

    id: int
    tweet_id: str
    action_type: ActionType
    created_at: datetime = Field(default_factory=_utcnow)
