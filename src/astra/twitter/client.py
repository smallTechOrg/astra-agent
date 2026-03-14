from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from datetime import UTC, datetime
from types import TracebackType

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from astra.twitter.models import SearchResult, Tweet, TweetMetrics, TwitterUser

logger = structlog.get_logger(__name__)

_API_BASE = "https://api.twitter.com/2"

_retry_transient = retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=30),
    reraise=True,
)


# ── Exceptions ───────────────────────────────────────────────────


class TwitterError(Exception):
    """Base exception for Twitter API errors."""


class TwitterAuthError(TwitterError):
    """Raised when authentication with the Twitter API fails."""


class TwitterRateLimitError(TwitterError):
    """Raised when a Twitter API rate limit is hit."""

    def __init__(self, message: str, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


# ── OAuth 1.0a ───────────────────────────────────────────────────


class _OAuth1Auth(httpx.Auth):
    """OAuth 1.0a request signing via HMAC-SHA1.

    Implements the Twitter OAuth 1.0a flow using only stdlib modules.
    """

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_secret: str,
    ) -> None:
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._access_token = access_token
        self._access_secret = access_secret

    def auth_flow(self, request: httpx.Request):
        """Sign the request with OAuth 1.0a parameters."""
        oauth_params = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self._access_token,
            "oauth_version": "1.0",
        }

        # Collect all parameters (OAuth + query string)
        all_params: dict[str, str] = dict(oauth_params)
        for key, value in request.url.params.items():
            all_params[key] = value

        # Build the signature base string
        sorted_params = "&".join(
            f"{_pct(k)}={_pct(v)}" for k, v in sorted(all_params.items())
        )
        base_url = str(request.url.copy_with(params=None))
        base_string = f"{request.method.upper()}&{_pct(base_url)}&{_pct(sorted_params)}"

        # Sign with HMAC-SHA1
        signing_key = f"{_pct(self._consumer_secret)}&{_pct(self._access_secret)}"
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode(),
                base_string.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()

        oauth_params["oauth_signature"] = signature

        # Build the Authorization header
        auth_header = "OAuth " + ", ".join(
            f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_params.items())
        )
        request.headers["Authorization"] = auth_header
        yield request


def _pct(value: str) -> str:
    """Percent-encode a string per RFC 5849."""
    return urllib.parse.quote(str(value), safe="")


# ── Response helpers ─────────────────────────────────────────────


def _check_response(response: httpx.Response) -> None:
    """Raise typed errors for common Twitter API status codes."""
    if response.status_code == 401:
        raise TwitterAuthError(f"Authentication failed: {response.text[:300]}")
    if response.status_code == 403:
        raise TwitterAuthError(f"Forbidden: {response.text[:300]}")
    if response.status_code == 429:
        reset_epoch = response.headers.get("x-rate-limit-reset")
        reset_at = (
            datetime.fromtimestamp(int(reset_epoch), tz=UTC)
            if reset_epoch
            else None
        )
        raise TwitterRateLimitError(
            f"Rate limit exceeded. Resets at {reset_at}",
            reset_at=reset_at,
        )
    response.raise_for_status()


def _parse_tweet(data: dict, includes: dict | None = None) -> Tweet:
    """Parse a tweet from the API v2 response shape."""
    metrics = data.get("public_metrics")
    # Resolve author username from includes if available
    author_username = None
    if includes and "users" in includes:
        for user in includes["users"]:
            if user["id"] == data.get("author_id"):
                author_username = user.get("username")
                break

    return Tweet(
        id=data["id"],
        text=data["text"],
        author_id=data.get("author_id", ""),
        author_username=author_username,
        created_at=data.get("created_at"),
        conversation_id=data.get("conversation_id"),
        public_metrics=TweetMetrics(**metrics) if metrics else None,
    )


# ── Client ───────────────────────────────────────────────────────


class TwitterClient:
    """Async Twitter API v2 client.

    Uses Bearer token for read operations and OAuth 1.0a for write operations.

    Usage::

        async with TwitterClient(...) as tw:
            tweet = await tw.post_tweet("Hello, world!")
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_secret: str,
        bearer_token: str,
    ) -> None:
        self._oauth = _OAuth1Auth(api_key, api_secret, access_token, access_secret)
        self._bearer_token = bearer_token
        self._read_client: httpx.AsyncClient | None = None
        self._write_client: httpx.AsyncClient | None = None
        self._user_id: str | None = None
        self._log = logger.bind(module="twitter")

    # ── Lifecycle ─────────────────────────────────────────────────

    def _ensure_read(self) -> httpx.AsyncClient:
        if self._read_client is None:
            self._read_client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._bearer_token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._read_client

    def _ensure_write(self) -> httpx.AsyncClient:
        if self._write_client is None:
            self._write_client = httpx.AsyncClient(
                auth=self._oauth,
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
        return self._write_client

    async def close(self) -> None:
        if self._read_client:
            await self._read_client.aclose()
            self._read_client = None
        if self._write_client:
            await self._write_client.aclose()
            self._write_client = None

    async def __aenter__(self) -> TwitterClient:
        self._ensure_read()
        self._ensure_write()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ── Internal ──────────────────────────────────────────────────

    async def _get_my_user_id(self) -> str:
        """Fetch and cache the authenticated user's ID."""
        if self._user_id is not None:
            return self._user_id
        client = self._ensure_write()
        response = await client.get(f"{_API_BASE}/users/me")
        _check_response(response)
        self._user_id = response.json()["data"]["id"]
        return self._user_id

    # ── Health ────────────────────────────────────────────────────

    @_retry_transient
    async def health_check(self) -> bool:
        """Verify credentials are valid."""
        self._log.debug("twitter.health_check")
        await self._get_my_user_id()
        self._log.info("twitter.health_check.ok", user_id=self._user_id)
        return True

    # ── Tweets ────────────────────────────────────────────────────

    @_retry_transient
    async def post_tweet(self, text: str, *, reply_to: str | None = None) -> Tweet:
        """Post a tweet. Enforces 280-character limit."""
        if len(text) > 280:
            raise TwitterError(f"Tweet exceeds 280 chars ({len(text)})")

        self._log.info("twitter.post_tweet", length=len(text), reply_to=reply_to)
        payload: dict = {"text": text}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}

        client = self._ensure_write()
        response = await client.post(f"{_API_BASE}/tweets", json=payload)
        _check_response(response)

        data = response.json()["data"]
        user_id = await self._get_my_user_id()
        tweet = Tweet(id=data["id"], text=data["text"], author_id=user_id)
        self._log.info("twitter.post_tweet.ok", tweet_id=tweet.id)
        return tweet

    @_retry_transient
    async def search_recent(self, query: str, *, max_results: int = 10) -> SearchResult:
        """Search recent tweets. Requires Twitter API Basic tier or higher."""
        self._log.info("twitter.search_recent", query=query, max_results=max_results)
        client = self._ensure_read()
        response = await client.get(
            f"{_API_BASE}/tweets/search/recent",
            params={
                "query": query,
                "max_results": min(max(max_results, 10), 100),
                "tweet.fields": "author_id,created_at,conversation_id,public_metrics",
                "expansions": "author_id",
                "user.fields": "username",
            },
        )
        _check_response(response)

        body = response.json()
        data = body.get("data", [])
        includes = body.get("includes")
        meta = body.get("meta", {})

        tweets = [_parse_tweet(t, includes) for t in data]
        self._log.info("twitter.search_recent.ok", count=len(tweets))
        return SearchResult(tweets=tweets, next_token=meta.get("next_token"))

    @_retry_transient
    async def get_tweet(self, tweet_id: str) -> Tweet:
        """Fetch a single tweet by ID."""
        client = self._ensure_read()
        response = await client.get(
            f"{_API_BASE}/tweets/{tweet_id}",
            params={
                "tweet.fields": "author_id,created_at,conversation_id,public_metrics",
                "expansions": "author_id",
                "user.fields": "username",
            },
        )
        _check_response(response)
        body = response.json()
        return _parse_tweet(body["data"], body.get("includes"))

    @_retry_transient
    async def get_user(self, username: str) -> TwitterUser:
        """Look up a user by their username."""
        client = self._ensure_read()
        response = await client.get(
            f"{_API_BASE}/users/by/username/{username}",
            params={"user.fields": "description,public_metrics"},
        )
        _check_response(response)
        data = response.json()["data"]
        metrics = data.get("public_metrics", {})
        return TwitterUser(
            id=data["id"],
            name=data["name"],
            username=data["username"],
            description=data.get("description"),
            followers_count=metrics.get("followers_count", 0),
            following_count=metrics.get("following_count", 0),
        )

    # ── Engagement ────────────────────────────────────────────────

    @_retry_transient
    async def like_tweet(self, tweet_id: str) -> bool:
        """Like a tweet."""
        user_id = await self._get_my_user_id()
        client = self._ensure_write()
        response = await client.post(
            f"{_API_BASE}/users/{user_id}/likes",
            json={"tweet_id": tweet_id},
        )
        _check_response(response)
        liked = response.json().get("data", {}).get("liked", False)
        self._log.info("twitter.like_tweet.ok", tweet_id=tweet_id, liked=liked)
        return liked

    @_retry_transient
    async def follow_user(self, user_id: str) -> bool:
        """Follow a user by their ID."""
        my_id = await self._get_my_user_id()
        client = self._ensure_write()
        response = await client.post(
            f"{_API_BASE}/users/{my_id}/following",
            json={"target_user_id": user_id},
        )
        _check_response(response)
        following = response.json().get("data", {}).get("following", False)
        self._log.info("twitter.follow_user.ok", target_user_id=user_id, following=following)
        return following
