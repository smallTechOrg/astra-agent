from __future__ import annotations

from types import TracebackType

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from astra.wordpress.models import WordPressPost, WordPressPostResponse

logger = structlog.get_logger(__name__)


# ── Exceptions ───────────────────────────────────────────────────


class WordPressError(Exception):
    """Base exception for WordPress API errors."""


class WordPressAuthError(WordPressError):
    """Raised when authentication with the WordPress API fails."""


class WordPressNotFoundError(WordPressError):
    """Raised when a requested WordPress resource is not found."""


# ── Retry policy ─────────────────────────────────────────────────

_retry_transient = retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=30),
    reraise=True,
)


# ── Helpers ──────────────────────────────────────────────────────


def _check_response(response: httpx.Response) -> None:
    """Raise typed errors for common HTTP status codes."""
    if response.status_code in (401, 403):
        raise WordPressAuthError(
            f"Authentication failed (HTTP {response.status_code}): {response.text[:200]}"
        )
    if response.status_code == 404:
        raise WordPressNotFoundError(
            f"Resource not found: {response.url}"
        )
    response.raise_for_status()


# ── Client ───────────────────────────────────────────────────────


class WordPressClient:
    """Async client for the WordPress REST API (v2).

    Supports Basic Authentication via application passwords and
    manages its own ``httpx.AsyncClient`` lifecycle.

    Usage::

        async with WordPressClient(url, user, pw) as wp:
            post = await wp.create_post(payload)
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Normalise: always point at the v2 REST root
        if "/wp-json/wp/v2" in self._base_url:
            self._api = self._base_url
        else:
            self._api = f"{self._base_url}/wp-json/wp/v2"

        self._auth = httpx.BasicAuth(username, app_password)
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._log = logger.bind(wordpress_url=self._base_url)

    # ── Lifecycle ─────────────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=self._auth,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> WordPressClient:
        self._ensure_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ── Health ────────────────────────────────────────────────────

    @_retry_transient
    async def health_check(self) -> bool:
        """Verify the WordPress REST API is reachable and credentials work."""
        self._log.debug("wordpress.health_check")
        client = self._ensure_client()
        response = await client.get(f"{self._api}/posts", params={"per_page": 1})
        _check_response(response)
        self._log.info("wordpress.health_check.ok")
        return True

    # ── Posts ─────────────────────────────────────────────────────

    @_retry_transient
    async def create_post(self, post: WordPressPost) -> WordPressPostResponse:
        """Create a new WordPress post."""
        payload = post.to_api_payload()
        self._log.info("wordpress.create_post", title=post.title, status=post.status.value)

        client = self._ensure_client()
        response = await client.post(f"{self._api}/posts", json=payload)
        _check_response(response)

        result = WordPressPostResponse.model_validate(response.json())
        self._log.info("wordpress.create_post.ok", wp_post_id=result.id, link=result.link)
        return result

    @_retry_transient
    async def update_post(self, post_id: int, post: WordPressPost) -> WordPressPostResponse:
        """Update an existing WordPress post."""
        payload = post.to_api_payload()
        self._log.info("wordpress.update_post", post_id=post_id)

        client = self._ensure_client()
        response = await client.post(f"{self._api}/posts/{post_id}", json=payload)
        _check_response(response)

        result = WordPressPostResponse.model_validate(response.json())
        self._log.info("wordpress.update_post.ok", wp_post_id=result.id)
        return result

    @_retry_transient
    async def get_post(self, post_id: int) -> WordPressPostResponse:
        """Fetch a single post by ID."""
        self._log.debug("wordpress.get_post", post_id=post_id)
        client = self._ensure_client()
        response = await client.get(f"{self._api}/posts/{post_id}")
        _check_response(response)
        return WordPressPostResponse.model_validate(response.json())

    @_retry_transient
    async def list_posts(
        self,
        *,
        status: str = "publish",
        per_page: int = 10,
        page: int = 1,
    ) -> list[WordPressPostResponse]:
        """List posts with optional filtering."""
        self._log.debug("wordpress.list_posts", status=status, per_page=per_page)
        client = self._ensure_client()
        response = await client.get(
            f"{self._api}/posts",
            params={"status": status, "per_page": per_page, "page": page},
        )
        _check_response(response)
        return [WordPressPostResponse.model_validate(p) for p in response.json()]

    @_retry_transient
    async def get_categories(self) -> list[dict]:
        """Fetch all categories."""
        client = self._ensure_client()
        response = await client.get(f"{self._api}/categories", params={"per_page": 100})
        _check_response(response)
        return response.json()

    @_retry_transient
    async def get_tags(self) -> list[dict]:
        """Fetch all tags."""
        client = self._ensure_client()
        response = await client.get(f"{self._api}/tags", params={"per_page": 100})
        _check_response(response)
        return response.json()
