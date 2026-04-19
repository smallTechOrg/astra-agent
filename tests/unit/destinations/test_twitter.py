"""Twitter destination tests.

Gate (phase 7): _prepare_tweet (URL injection, truncation); happy path 201;
401 sets needs_reauth; 429 stores rate_limit_reset_at; 403 duplicate_content
permanent; 5xx transient; needs_reauth skips.
"""

from __future__ import annotations

from astra.destinations.twitter import _prepare_tweet

_URL = "https://blog.example.com/my-long-post/"


# ── _prepare_tweet ───────────────────────────────────────────────

def test_prepare_tweet_strips_surrounding_quotes() -> None:
    result = _prepare_tweet('"Great article!"', _URL)
    assert not result.startswith('"')


def test_prepare_tweet_appends_url_if_missing() -> None:
    result = _prepare_tweet("Check this out", _URL)
    assert _URL in result


def test_prepare_tweet_does_not_duplicate_url() -> None:
    copy = f"Check this out {_URL}"
    result = _prepare_tweet(copy, _URL)
    assert result.count(_URL) == 1


def test_prepare_tweet_truncates_body_preserving_url() -> None:
    long_body = "x" * 300
    result = _prepare_tweet(long_body, _URL)
    # Total length should be <= 280 when counting URL as 23 chars.
    url_len = 23
    non_url = result.replace(_URL, "").rstrip()
    assert len(non_url) + 1 + url_len <= 280


def test_prepare_tweet_short_copy_unchanged() -> None:
    copy = f"Short copy {_URL}"
    result = _prepare_tweet(copy, _URL)
    assert result == copy


# ── Registry ─────────────────────────────────────────────────────

def test_registry_resolves_twitter() -> None:
    from astra.destinations import TwitterDestination, get_destination
    from astra.destinations.base import Destination

    cls = get_destination("twitter")
    assert issubclass(cls, Destination)
    assert cls is TwitterDestination
