"""Shared domain types used across sources, destinations, cadences, and the daemon.

These are pure dataclasses / typed unions — no I/O, no DB, no config. Every
abstraction in spec/product/02-architecture.md that names a return type has a
matching class here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from datetime import datetime

# ── PublishEvent ─────────────────────────────────────────────────

@dataclass(frozen=True)
class PublishEvent:
    """A single WordPress post surfaced by a Source.poll() call.

    Mirrors the `publish_events` table row but is the in-memory form passed
    between Source → Distributor.  `db_id` is None until the row is persisted.
    """

    tenant_id: str
    source_name: str
    source_post_id: str
    title: str
    url: str
    excerpt: str | None
    published_at: datetime
    db_id: int | None = field(default=None, compare=False)


# ── PublishResult ────────────────────────────────────────────────

@dataclass(frozen=True)
class PublishSuccess:
    platform_post_id: str
    copy: str


@dataclass(frozen=True)
class PublishSkipped:
    reason: str


@dataclass(frozen=True)
class PublishFailure:
    error: str
    transient: bool


PublishResult = PublishSuccess | PublishSkipped | PublishFailure


# ── TweetResult ──────────────────────────────────────────────────

@dataclass(frozen=True)
class TweetSent:
    cadence_name: str
    tweet_id: str
    text: str


@dataclass(frozen=True)
class TweetSkipped:
    cadence_name: str
    reason: str


@dataclass(frozen=True)
class TweetFailed:
    cadence_name: str
    error: str
    transient: bool


TweetResult = TweetSent | TweetSkipped | TweetFailed


# ── HealthStatus ─────────────────────────────────────────────────

class HealthStatus(BaseModel):
    """Return type of Destination.health_check(tenant).

    `ok` is the single source-of-truth. `reason` is only set when not ok.
    `needs_reauth` signals the token is expired / revoked (distinct from a
    transient network error, which would also set ok=False but not this flag).
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    reason: str | None = None
    needs_reauth: bool = False
    degraded: bool = False


# ── Convenience factories ────────────────────────────────────────

def health_ok() -> HealthStatus:
    return HealthStatus(ok=True)


def health_reauth(reason: str) -> HealthStatus:
    return HealthStatus(ok=False, reason=reason, needs_reauth=True)


def health_degraded(reason: str) -> HealthStatus:
    return HealthStatus(ok=False, reason=reason, degraded=True)


__all__ = [
    "PublishEvent",
    "PublishFailure",
    "PublishResult",
    "PublishSkipped",
    "PublishSuccess",
    "TweetFailed",
    "TweetResult",
    "TweetSent",
    "TweetSkipped",
    "HealthStatus",
    "health_degraded",
    "health_ok",
    "health_reauth",
]
