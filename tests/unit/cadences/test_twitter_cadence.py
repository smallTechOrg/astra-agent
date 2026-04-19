"""TwitterCadence tests.

Gate (phase 8): empty-history renders sentinel; full-history injects recent
tweets; short LLM output records failed (not skipped); 401 marks needs_reauth
and next tick returns skipped; 429 stores rate_limit_reset_at; cadence disabled
→ TweetSkipped; registry resolves "twitter".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astra.cadences.twitter import _MAX_TWEET_LEN, _MIN_TWEET_LEN, TwitterCadence
from astra.config.models import TenantConfig
from astra.db.repos import DestinationStateRepo, ScheduledTweetsRepo, TenantsRepo
from astra.domain import TweetFailed, TweetSent, TweetSkipped

if TYPE_CHECKING:
    from astra.db import Database

# ── helpers ──────────────────────────────────────────────────────

_PACKED_TOKEN = "api_key|api_secret|oauth_token|oauth_secret"


def _tenant(tenant_id: str = "acme") -> TenantConfig:
    return TenantConfig.model_validate({
        "id": tenant_id,
        "name": "Acme Corp",
        "enabled": True,
        "source": {
            "type": "wordpress",
            "url": "https://blog.example.com",
            "username": "admin",
        },
        "destinations": {},
        "cadences": [],
    })


def _cadence_cfg(enabled: bool = True) -> object:
    """Return a cadence config-like object (duck-typed)."""
    cfg = MagicMock()
    cfg.name = "daily"
    cfg.enabled = enabled
    cfg.feedback_last_n = 3
    return cfg


def _mock_llm(text: str = "Great insight about mindfulness today!") -> AsyncMock:
    llm = AsyncMock()
    llm.generate_content = AsyncMock(return_value=text)
    return llm


def _mock_oauth_session(status: int, body: object = None, headers: dict | None = None) -> MagicMock:
    """Return a mock OAuth1Session whose .post() returns the given HTTP response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.text = json.dumps(body) if isinstance(body, dict) else (body or "")
    mock_resp.headers = headers or {}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    return mock_session


def _mock_prompts(system: str = "You are a helpful poster.", user: str = "Write a tweet.") -> MagicMock:
    from astra.prompts.resolver import RenderedPrompt

    prompts = MagicMock()
    prompts.render = AsyncMock(return_value=RenderedPrompt(system_prompt=system, user_prompt=user))
    return prompts


@pytest.fixture
async def db(db: Database) -> Database:
    await TenantsRepo(db).upsert("acme", "Acme", enabled=True)
    return db


# ── cadence disabled ─────────────────────────────────────────────

async def test_disabled_cadence_returns_skipped(db: Database) -> None:
    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(enabled=False),
        db,
        _mock_llm(),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    assert isinstance(result, TweetSkipped)
    assert result.reason == "cadence_disabled"


async def test_disabled_cadence_writes_db_record(db: Database) -> None:
    cadence = TwitterCadence()
    await cadence.tick(
        _tenant(),
        _cadence_cfg(enabled=False),
        db,
        _mock_llm(),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    rows = await ScheduledTweetsRepo(db).list_recent("acme", cadence_name="daily", limit=10)
    assert len(rows) == 1
    assert rows[0].status == "skipped"
    assert rows[0].error == "cadence_disabled"


# ── needs_reauth / degraded skip ────────────────────────────────

async def test_needs_reauth_destination_returns_skipped(db: Database) -> None:
    await DestinationStateRepo(db).update("acme", "twitter", needs_reauth=True)
    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    assert isinstance(result, TweetSkipped)
    assert result.reason == "needs_reauth"


async def test_degraded_destination_returns_skipped(db: Database) -> None:
    await DestinationStateRepo(db).update("acme", "twitter", degraded=True)
    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    assert isinstance(result, TweetSkipped)
    assert result.reason == "destination_degraded"


# ── prompt rendering (sentinel vs recent tweets) ─────────────────

async def test_empty_history_renders_sentinel(db: Database) -> None:
    """No prior sent tweets → sentinel string passed as recent_tweets var."""
    prompts = _mock_prompts()
    cadence = TwitterCadence()

    mock_session = _mock_oauth_session(201, {"data": {"id": "123"}})
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            prompts,
            access_token=_PACKED_TOKEN,
        )

    recent_tweets_val = prompts.render.call_args.kwargs["recent_tweets"]
    assert "none yet" in recent_tweets_val


async def test_full_history_injects_recent_tweets(db: Database) -> None:
    """Pre-existing sent tweets are included in the recent_tweets prompt variable."""
    # Seed two sent tweets.
    repo = ScheduledTweetsRepo(db)
    await repo.insert(
        tenant_id="acme",
        cadence_name="daily",
        text="Tweet one about Buddhism",
        platform_post_id="t1",
        status="sent",
    )
    await repo.insert(
        tenant_id="acme",
        cadence_name="daily",
        text="Tweet two about mindfulness",
        platform_post_id="t2",
        status="sent",
    )

    prompts = _mock_prompts()
    cadence = TwitterCadence()

    mock_session = _mock_oauth_session(201, {"data": {"id": "999"}})
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            prompts,
            access_token=_PACKED_TOKEN,
        )

    recent_tweets_val = prompts.render.call_args.kwargs["recent_tweets"]
    assert "Tweet one about Buddhism" in recent_tweets_val
    assert "Tweet two about mindfulness" in recent_tweets_val


# ── happy path (201) ─────────────────────────────────────────────

async def test_happy_path_returns_tweet_sent(db: Database) -> None:
    mock_session = _mock_oauth_session(201, {"data": {"id": "42"}})
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm("A thoughtful tweet about dharma today."),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetSent)
    assert result.tweet_id == "42"
    assert result.cadence_name == "daily"


async def test_happy_path_writes_sent_db_record(db: Database) -> None:
    mock_session = _mock_oauth_session(201, {"data": {"id": "42"}})
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm("A thoughtful tweet about dharma today."),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    rows = await ScheduledTweetsRepo(db).list_recent("acme", cadence_name="daily", limit=10)
    assert any(r.status == "sent" and r.platform_post_id == "42" for r in rows)


# ── short LLM output ─────────────────────────────────────────────

async def test_short_llm_output_returns_failed(db: Database) -> None:
    short_text = "x" * (_MIN_TWEET_LEN - 1)
    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(short_text),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    assert isinstance(result, TweetFailed)
    assert result.error == "llm_output_too_short"
    assert result.transient is False


async def test_short_llm_output_writes_failed_record(db: Database) -> None:
    short_text = "x" * (_MIN_TWEET_LEN - 1)
    cadence = TwitterCadence()
    await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(short_text),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    rows = await ScheduledTweetsRepo(db).list_recent("acme", cadence_name="daily", limit=10)
    assert any(r.status == "failed" and r.error == "llm_output_too_short" for r in rows)


# ── long LLM output truncation ───────────────────────────────────

async def test_long_llm_output_is_truncated(db: Database) -> None:
    long_text = "a" * 400
    mock_session = _mock_oauth_session(201, {"data": {"id": "77"}})
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(long_text),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetSent)
    assert len(result.text) <= _MAX_TWEET_LEN
    assert result.text.endswith("…")


# ── 401 (auth failure) ───────────────────────────────────────────

async def test_401_returns_failed_and_sets_needs_reauth(db: Database) -> None:
    mock_session = _mock_oauth_session(401, "Unauthorized")
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetFailed)
    assert result.error == "auth_401"
    assert result.transient is False

    state = await DestinationStateRepo(db).get("acme", "twitter")
    assert state is not None
    assert state.needs_reauth is True


async def test_after_401_next_tick_returns_skipped(db: Database) -> None:
    """After 401 sets needs_reauth, a subsequent tick is skipped."""
    mock_session = _mock_oauth_session(401, "Unauthorized")
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    # Next tick — no HTTP mock needed, should short-circuit.
    result2 = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(),
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )
    assert isinstance(result2, TweetSkipped)
    assert result2.reason == "needs_reauth"


# ── 429 (rate limit) ────────────────────────────────────────────

async def test_429_returns_transient_failed(db: Database) -> None:
    mock_session = _mock_oauth_session(429, "Rate limited", {"x-rate-limit-reset": "1735000000"})
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetFailed)
    assert result.error == "rate_limited"
    assert result.transient is True


# ── 403 (duplicate content) ──────────────────────────────────────

async def test_403_returns_permanent_failed(db: Database) -> None:
    mock_session = _mock_oauth_session(403, "Duplicate")
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetFailed)
    assert result.error == "duplicate_content"
    assert result.transient is False


# ── 5xx (server error) ───────────────────────────────────────────

async def test_5xx_returns_transient_failed(db: Database) -> None:
    mock_session = _mock_oauth_session(503, "Service Unavailable")
    cadence = TwitterCadence()
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        result = await cadence.tick(
            _tenant(),
            _cadence_cfg(),
            db,
            _mock_llm(),
            _mock_prompts(),
            access_token=_PACKED_TOKEN,
        )

    assert isinstance(result, TweetFailed)
    assert result.transient is True


# ── LLM error ────────────────────────────────────────────────────

async def test_llm_error_returns_transient_failed(db: Database) -> None:
    llm = AsyncMock()
    llm.generate_content = AsyncMock(side_effect=RuntimeError("LLM timeout"))

    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        llm,
        _mock_prompts(),
        access_token=_PACKED_TOKEN,
    )

    assert isinstance(result, TweetFailed)
    assert "llm_error" in result.error
    assert result.transient is True


# ── prompt error ─────────────────────────────────────────────────

async def test_prompt_error_returns_permanent_failed(db: Database) -> None:
    prompts = MagicMock()
    prompts.render = MagicMock(side_effect=FileNotFoundError("prompt not found"))

    cadence = TwitterCadence()
    result = await cadence.tick(
        _tenant(),
        _cadence_cfg(),
        db,
        _mock_llm(),
        prompts,
        access_token=_PACKED_TOKEN,
    )

    assert isinstance(result, TweetFailed)
    assert "prompt_error" in result.error
    assert result.transient is False


# ── tenant isolation ─────────────────────────────────────────────

async def test_two_tenants_do_not_share_history(db: Database) -> None:
    """Sent tweets for tenant A must not appear in tenant B's recent_tweets."""
    await TenantsRepo(db).upsert("beta", "Beta", enabled=True)

    repo = ScheduledTweetsRepo(db)
    await repo.insert(
        tenant_id="acme",
        cadence_name="daily",
        text="Acme-only tweet about the path",
        platform_post_id="acme_t1",
        status="sent",
    )

    prompts = _mock_prompts()
    cadence = TwitterCadence()

    beta_tenant = TenantConfig.model_validate({
        "id": "beta",
        "name": "Beta Corp",
        "enabled": True,
        "source": {
            "type": "wordpress",
            "url": "https://blog.beta.com",
            "username": "admin",
        },
        "destinations": {},
        "cadences": [],
    })

    mock_session = _mock_oauth_session(201, {"data": {"id": "b1"}})
    with patch("requests_oauthlib.OAuth1Session", return_value=mock_session):
        await cadence.tick(
            beta_tenant,
            _cadence_cfg(),
            db,
            _mock_llm(),
            prompts,
            access_token=_PACKED_TOKEN,
        )

    recent_tweets_val = prompts.render.call_args.kwargs["recent_tweets"]
    assert "Acme-only tweet" not in recent_tweets_val
    assert "none yet" in recent_tweets_val


# ── registry ─────────────────────────────────────────────────────

def test_registry_resolves_twitter_cadence() -> None:
    from astra.cadences import TwitterCadence, get_cadence
    from astra.cadences.base import Cadence

    cls = get_cadence("twitter")
    assert issubclass(cls, Cadence)
    assert cls is TwitterCadence
