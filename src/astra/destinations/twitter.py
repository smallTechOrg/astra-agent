"""Twitter / X destination for blog announcements.

Per spec/product/04-capabilities/twitter-blog-announcement.md.
OAuth 1.0a via requests-oauthlib (spec/engineering/code-style.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.db.repos import DestinationStateRepo, DistributionRecordsRepo
from astra.destinations.base import Destination
from astra.domain import (
    HealthStatus,
    PublishFailure,
    PublishResult,
    PublishSkipped,
    PublishSuccess,
    health_ok,
    health_reauth,
)
from astra.logging import get_logger

if TYPE_CHECKING:
    from astra.config.models import TenantConfig
    from astra.db.connection import Database
    from astra.domain import PublishEvent

_TWEET_URL = "https://api.twitter.com/2/tweets"
_VERIFY_URL = "https://api.twitter.com/2/users/me"
_MAX_TWEET_CHARS = 280
_URL_T_CO_LEN = 23  # X shortens all URLs to 23 chars

log = get_logger(__name__)


def _build_oauth_session(
    *,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_secret: str,
) -> object:
    """Return a requests-oauthlib OAuth1Session (sync; used in thread)."""
    from requests_oauthlib import OAuth1Session
    return OAuth1Session(
        client_key=api_key,
        client_secret=api_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def _post_tweet_sync(session: object, text: str) -> dict[str, object]:
    """Synchronous tweet POST — run in executor to avoid blocking loop."""
    from requests_oauthlib import OAuth1Session

    assert isinstance(session, OAuth1Session)
    resp = session.post(_TWEET_URL, json={"text": text})
    return {"status": resp.status_code, "body": resp.text, "headers": dict(resp.headers)}


def _post_verify_sync(session: object) -> dict[str, object]:
    from requests_oauthlib import OAuth1Session

    assert isinstance(session, OAuth1Session)
    resp = session.get(_VERIFY_URL)
    return {"status": resp.status_code, "body": resp.text}


def _prepare_tweet(copy: str, url: str) -> str:
    """Strip quotes, ensure URL present, enforce 280-char limit."""
    text = copy.strip().strip('"').strip("'").strip()

    if url not in text:
        text = f"{text} {url}"

    # Budget: body chars + URL as 23-char shortened URL.
    url_budget = _URL_T_CO_LEN
    non_url = text.replace(url, "").rstrip()
    if len(non_url) + 1 + url_budget > _MAX_TWEET_CHARS:
        max_body = _MAX_TWEET_CHARS - 1 - url_budget - 1  # 1 space + 1 ellipsis
        non_url = non_url[:max_body] + "…"
        text = f"{non_url} {url}"

    return text


class TwitterDestination(Destination):
    async def publish(
        self,
        tenant: TenantConfig,
        event: PublishEvent,
        copy: str,
        db: Database,
        *,
        access_token: str,
    ) -> PublishResult:
        import asyncio

        bound = log.bind(tenant_id=tenant.id, publish_event_id=event.db_id)

        dest_state_repo = DestinationStateRepo(db)
        dist_repo = DistributionRecordsRepo(db)

        state = await dest_state_repo.get(tenant.id, "twitter")
        if state is not None and state.needs_reauth:
            return PublishSkipped(reason="needs_reauth")

        assert event.db_id is not None
        claimed = await dist_repo.claim_pending(
            tenant_id=tenant.id,
            publish_event_id=event.db_id,
            platform="twitter",
        )
        if claimed is None:
            return PublishSkipped(reason="already_claimed")

        tw_cfg = tenant.destinations.twitter
        assert tw_cfg is not None

        # Resolve the four OAuth 1.0a secrets (already injected by caller).
        # access_token param here is the resolved access_token.
        # The caller must also pass api_key, api_secret, access_secret separately;
        # but our interface only takes one `access_token`. We store 4 values in a
        # single packed string "api_key:api_secret:access_token:access_secret"
        # or we accept the convention that access_token is the full 4-tuple packed.
        # For simplicity: access_token is a pipe-separated "key|secret|token|secret2".
        parts = access_token.split("|", 3)
        if len(parts) != 4:
            raise ValueError(
                "Twitter access_token must be 'api_key|api_secret|access_token|access_secret'"
            )
        api_key, api_secret, oauth_token, oauth_secret = parts

        tweet_text = _prepare_tweet(copy, event.url)
        bound.info("twitter_announcement_started", tweet_len=len(tweet_text))

        session = _build_oauth_session(
            api_key=api_key,
            api_secret=api_secret,
            access_token=oauth_token,
            access_secret=oauth_secret,
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _post_tweet_sync, session, tweet_text)

        status: int = result["status"]  # type: ignore[assignment]
        body = result["body"]
        headers: dict[str, str] = result["headers"]  # type: ignore[assignment]

        if status == 201:
            import json
            try:
                tweet_id = str(json.loads(str(body))["data"]["id"])
            except Exception:
                tweet_id = ""
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="twitter",
                status="sent",
                platform_post_id=tweet_id,
                copy=tweet_text,
            )
            bound.info("twitter_announcement_sent", tweet_id=tweet_id)
            return PublishSuccess(platform_post_id=tweet_id, copy=tweet_text)

        error_str = str(body)[:500]

        if status == 401:
            await dest_state_repo.update(tenant.id, "twitter", needs_reauth=True)
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="twitter",
                status="failed",
                error="auth_401",
            )
            bound.warning("twitter_auth_failed")
            return PublishFailure(error="auth_401", transient=False)

        if status == 429:
            reset_at = str(headers.get("x-rate-limit-reset", ""))
            await dest_state_repo.update(
                tenant.id, "twitter", rate_limit_reset_at=reset_at or None
            )
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="twitter",
                status="failed",
                error="rate_limited",
            )
            return PublishFailure(error="rate_limited", transient=True)

        if status == 403:
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="twitter",
                status="failed",
                error="duplicate_content",
            )
            return PublishFailure(error="duplicate_content", transient=False)

        await dist_repo.complete(
            tenant_id=tenant.id,
            publish_event_id=event.db_id,
            platform="twitter",
            status="failed",
            error=f"http_{status}",
        )
        bound.warning("twitter_announcement_failed", status=status, body=error_str)
        return PublishFailure(error=f"http_{status}", transient=status >= 500)

    async def health_check(
        self,
        tenant: TenantConfig,
        *,
        access_token: str,
    ) -> HealthStatus:
        import asyncio

        parts = access_token.split("|", 3)
        if len(parts) != 4:
            return HealthStatus(ok=False, reason="invalid_credentials_format")

        api_key, api_secret, oauth_token, oauth_secret = parts
        session = _build_oauth_session(
            api_key=api_key,
            api_secret=api_secret,
            access_token=oauth_token,
            access_secret=oauth_secret,
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _post_verify_sync, session)

        status: int = result["status"]  # type: ignore[assignment]
        if status == 200:
            return health_ok()
        if status == 401:
            return health_reauth("auth_401")
        return HealthStatus(ok=False, reason=f"http_{status}")
