"""Domain type smoke tests — every typed union variant is reachable."""

from __future__ import annotations

from astra.domain import (
    PublishEvent,
    PublishFailure,
    PublishSkipped,
    PublishSuccess,
    TweetFailed,
    TweetSent,
    TweetSkipped,
    health_degraded,
    health_ok,
    health_reauth,
)


def test_publish_success_carries_post_id_and_copy() -> None:
    r = PublishSuccess(platform_post_id="abc123", copy="Hello world")
    assert r.platform_post_id == "abc123"
    assert r.copy == "Hello world"


def test_publish_skipped_carries_reason() -> None:
    r = PublishSkipped(reason="needs_reauth")
    assert r.reason == "needs_reauth"


def test_publish_failure_transient_flag() -> None:
    r = PublishFailure(error="connection reset", transient=True)
    assert r.transient is True


def test_tweet_sent() -> None:
    r = TweetSent(cadence_name="hourly", tweet_id="t1", text="hi")
    assert r.tweet_id == "t1"


def test_tweet_skipped() -> None:
    r = TweetSkipped(cadence_name="hourly", reason="too_recent")
    assert r.reason == "too_recent"


def test_tweet_failed_permanent() -> None:
    r = TweetFailed(cadence_name="hourly", error="403", transient=False)
    assert r.transient is False


def test_health_ok_factory() -> None:
    h = health_ok()
    assert h.ok is True
    assert h.reason is None
    assert h.needs_reauth is False


def test_health_reauth_factory() -> None:
    h = health_reauth("token expired")
    assert h.ok is False
    assert h.needs_reauth is True
    assert h.reason == "token expired"


def test_health_degraded_factory() -> None:
    h = health_degraded("rate limited")
    assert h.ok is False
    assert h.degraded is True


def test_health_status_immutable() -> None:
    import pytest
    from pydantic import ValidationError

    h = health_ok()
    with pytest.raises((ValidationError, TypeError)):
        h.ok = False  # type: ignore[misc]


def test_publish_event_frozen() -> None:
    import dataclasses

    import pytest

    e = PublishEvent(
        tenant_id="t",
        source_name="wp",
        source_post_id="p1",
        title="Hello",
        url="https://x.example",
        excerpt=None,
        published_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.title = "changed"  # type: ignore[misc]
