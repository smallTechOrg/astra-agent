from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LinkedInShare(BaseModel):
    """Payload for creating a LinkedIn share/post."""

    model_config = ConfigDict(strict=True, frozen=True)

    text: str
    url: str | None = None
    title: str | None = None
    description: str | None = None


class LinkedInShareResponse(BaseModel):
    """Response returned after successfully creating a LinkedIn share."""

    model_config = ConfigDict(strict=True, frozen=True)

    id: str
    activity: str
