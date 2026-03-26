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

from astra.linkedin.models import LinkedInShare, LinkedInShareResponse

logger = structlog.get_logger(__name__)


# ── Exceptions ───────────────────────────────────────────────────


class LinkedInError(Exception):
    """Base exception for LinkedIn API errors."""


class LinkedInAuthError(LinkedInError):
    """Raised when authentication with the LinkedIn API fails."""


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
        body = response.text[:300]
        hint = ""
        if "author" in body and "ACCESS_DENIED" in body:
            hint = (
                "\n\nHint: To post as an organization page, your LinkedIn app needs the "
                "'Community Management' product (grants w_organization_social scope).\n"
                "Add it at linkedin.com/developers/apps → Products, then re-run: "
                "astra auth linkedin --client-id ... --client-secret ..."
            )
        raise LinkedInAuthError(
            f"Authentication failed (HTTP {response.status_code}): {body}{hint}"
        )
    if response.status_code >= 400:
        raise LinkedInError(
            f"LinkedIn API error (HTTP {response.status_code}): {response.text[:300]}"
        )


# ── Client ───────────────────────────────────────────────────────


class LinkedInClient:
    """Async client for the LinkedIn API.

    Supports posting to both personal profiles (via ``/v2/posts``) and
    organisation pages (via ``/v2/ugcPosts``).  The mode is determined by
    whether an ``organization_id`` is provided at construction time.

    Usage::

        async with LinkedInClient(token) as li:
            resp = await li.share_post(LinkedInShare(text="Hello world"))
    """

    _BASE_URL = "https://api.linkedin.com"

    def __init__(
        self,
        access_token: str,
        organization_id: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._access_token = access_token
        self._organization_id = organization_id
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._person_urn: str | None = None
        self._log = logger.bind(
            linkedin_org=organization_id or "personal",
        )

    # ── Lifecycle ─────────────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._BASE_URL,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                    "LinkedIn-Version": "202401",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> LinkedInClient:
        self._ensure_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ── Profile ──────────────────────────────────────────────────

    @_retry_transient
    async def get_profile(self) -> dict:
        """Fetch the current authenticated user's profile via ``/v2/userinfo``."""
        self._log.debug("linkedin.get_profile")
        client = self._ensure_client()
        response = await client.get("/v2/userinfo")
        _check_response(response)
        data: dict = response.json()
        self._log.info("linkedin.get_profile.ok", sub=data.get("sub"))
        return data

    async def _get_person_urn(self) -> str:
        """Return the authenticated user's person URN, fetching it if needed."""
        if self._person_urn is None:
            profile = await self.get_profile()
            sub = profile.get("sub")
            if not sub:
                msg = (
                    "Unable to resolve person URN: "
                    "'sub' field missing from /v2/userinfo response."
                )
                raise LinkedInError(msg)
            self._person_urn = f"urn:li:person:{sub}"
        return self._person_urn

    # ── Health check ─────────────────────────────────────────────

    @_retry_transient
    async def health_check(self) -> bool:
        """Verify the access token is valid by calling ``/v2/userinfo``."""
        self._log.debug("linkedin.health_check")
        client = self._ensure_client()
        response = await client.get("/v2/userinfo")
        _check_response(response)
        self._log.info("linkedin.health_check.ok")
        return True

    # ── Posting ──────────────────────────────────────────────────

    @_retry_transient
    async def share_post(self, share: LinkedInShare) -> LinkedInShareResponse:
        """Create a LinkedIn share/post.

        Uses the UGC Posts API (``/v2/ugcPosts``) when an organisation ID is
        configured, or the Posts API (``/v2/posts``) for personal profiles.

        Parameters
        ----------
        share:
            The share payload containing text and optional link metadata.

        Returns
        -------
        LinkedInShareResponse
            Contains the post ``id`` and ``activity`` URN.
        """
        if self._organization_id:
            return await self._share_as_organization(share)
        return await self._share_as_person(share)

    async def _share_as_organization(self, share: LinkedInShare) -> LinkedInShareResponse:
        """Post on behalf of an organisation via the unified Posts API."""
        author = f"urn:li:organization:{self._organization_id}"
        self._log.info("linkedin.share_org", org=self._organization_id)

        payload: dict = {
            "author": author,
            "commentary": share.text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }

        if share.url:
            article: dict = {"source": share.url}
            if share.title:
                article["title"] = share.title
            if share.description:
                article["description"] = share.description
            payload["content"] = {"article": article}

        client = self._ensure_client()
        response = await client.post("/v2/posts", json=payload)
        _check_response(response)

        post_id = response.headers.get("X-RestLi-Id", "")
        self._log.info("linkedin.share_org.ok", post_id=post_id)
        return LinkedInShareResponse(id=str(post_id), activity=str(post_id))

    async def _share_as_person(self, share: LinkedInShare) -> LinkedInShareResponse:
        """Post as a personal profile via the Posts API."""
        person_urn = await self._get_person_urn()
        self._log.info("linkedin.share_personal", author=person_urn)

        payload: dict = {
            "author": person_urn,
            "commentary": share.text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }

        # Attach article content if a URL is provided
        if share.url:
            article: dict = {
                "source": share.url,
            }
            if share.title:
                article["title"] = share.title
            if share.description:
                article["description"] = share.description

            payload["content"] = {
                "article": article,
            }

        client = self._ensure_client()
        response = await client.post("/v2/posts", json=payload)
        _check_response(response)

        # The Posts API returns the post URN in the X-RestLi-Id header
        post_id = response.headers.get("X-RestLi-Id", "")
        # For the Posts API, the activity URN typically mirrors the post URN
        activity = post_id

        self._log.info("linkedin.share_personal.ok", post_id=post_id)
        return LinkedInShareResponse(id=str(post_id), activity=str(activity))
