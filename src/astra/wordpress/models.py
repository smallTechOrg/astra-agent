from __future__ import annotations

import enum
from datetime import datetime  # noqa: TC003 — required at runtime by Pydantic

from pydantic import BaseModel, ConfigDict, Field


class PostStatus(enum.StrEnum):
    """Valid statuses when creating or updating a WordPress post."""

    DRAFT = "draft"
    PUBLISH = "publish"


class WordPressPost(BaseModel):
    """Payload for creating or updating a WordPress post via the REST API."""

    model_config = ConfigDict(strict=True)

    title: str
    content: str
    excerpt: str = ""
    status: PostStatus = PostStatus.DRAFT
    slug: str = ""
    categories: list[int] = Field(default_factory=list)
    tags: list[int] = Field(default_factory=list)
    featured_media: int | None = None

    def to_api_payload(self) -> dict[str, object]:
        """Serialize to the dict shape the WordPress REST API expects."""
        payload: dict[str, object] = {
            "title": self.title,
            "content": self.content,
            "status": self.status.value,
        }
        if self.excerpt:
            payload["excerpt"] = self.excerpt
        if self.slug:
            payload["slug"] = self.slug
        if self.categories:
            payload["categories"] = self.categories
        if self.tags:
            payload["tags"] = self.tags
        if self.featured_media is not None:
            payload["featured_media"] = self.featured_media
        return payload


class RenderedField(BaseModel):
    """WordPress REST API returns some fields as ``{"rendered": "..."}``."""

    model_config = ConfigDict(strict=True)

    rendered: str


class WordPressPostResponse(BaseModel):
    """Subset of fields returned by the WordPress REST API for a post."""

    model_config = ConfigDict(strict=False)

    id: int
    link: str
    status: str
    date: datetime
    title: RenderedField
    modified: datetime


class ContentBrief(BaseModel):
    """High-level brief that drives AI content generation for a blog post."""

    model_config = ConfigDict(strict=True)

    topic: str
    tone: str = "informative"
    target_word_count: int = 1500
    keywords: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
