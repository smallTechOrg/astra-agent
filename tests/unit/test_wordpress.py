from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from astra.wordpress.client import (
    WordPressAuthError,
    WordPressClient,
    WordPressNotFoundError,
)
from astra.wordpress.models import PostStatus, WordPressPost

BASE_URL = "http://wp.test.local"
API_URL = f"{BASE_URL}/wp-json/wp/v2"


def _make_post_response(
    post_id: int = 1,
    title: str = "Test Post",
    status: str = "draft",
    link: str = "http://wp.test.local/?p=1",
) -> dict:
    """Build a fake WordPress REST API post response."""
    now = datetime.now(UTC).isoformat()
    return {
        "id": post_id,
        "link": link,
        "status": status,
        "date": now,
        "title": {"rendered": title},
        "modified": now,
    }


@pytest.fixture()
def wp_client() -> WordPressClient:
    return WordPressClient(
        base_url=BASE_URL,
        username="testuser",
        app_password="testpass",
    )


class TestCreatePost:
    """Test WordPressClient.create_post."""

    @respx.mock
    async def test_create_post_success(self, wp_client: WordPressClient) -> None:
        response_data = _make_post_response(post_id=42, title="New Post", status="draft")
        respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=response_data)
        )

        async with wp_client:
            post = WordPressPost(title="New Post", content="<p>Body</p>", status=PostStatus.DRAFT)
            result = await wp_client.create_post(post)

        assert result.id == 42
        assert result.title.rendered == "New Post"
        assert result.status == "draft"

    @respx.mock
    async def test_create_post_publish(self, wp_client: WordPressClient) -> None:
        response_data = _make_post_response(post_id=43, title="Published", status="publish")
        respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=response_data)
        )

        async with wp_client:
            post = WordPressPost(
                title="Published",
                content="<p>Content</p>",
                status=PostStatus.PUBLISH,
            )
            result = await wp_client.create_post(post)

        assert result.id == 43
        assert result.status == "publish"


class TestHealthCheck:
    """Test WordPressClient.health_check."""

    @respx.mock
    async def test_health_check_success(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_post_response()])
        )

        async with wp_client:
            result = await wp_client.health_check()

        assert result is True


class TestAuthError:
    """Test that 401/403 responses raise WordPressAuthError."""

    @respx.mock
    async def test_401_raises_auth_error(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(
                401, json={"code": "rest_cannot_read", "message": "Unauthorized"}
            )
        )

        async with wp_client:
            with pytest.raises(WordPressAuthError, match="Authentication failed"):
                await wp_client.health_check()

    @respx.mock
    async def test_403_raises_auth_error(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )

        async with wp_client:
            with pytest.raises(WordPressAuthError, match="Authentication failed"):
                await wp_client.health_check()


class TestNotFoundError:
    """Test that 404 responses raise WordPressNotFoundError."""

    @respx.mock
    async def test_404_raises_not_found(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts/9999").mock(
            return_value=httpx.Response(404, json={"code": "rest_post_invalid_id"})
        )

        async with wp_client:
            with pytest.raises(WordPressNotFoundError, match="not found"):
                await wp_client.get_post(9999)


class TestListPosts:
    """Test WordPressClient.list_posts."""

    @respx.mock
    async def test_list_posts_returns_list(self, wp_client: WordPressClient) -> None:
        posts = [
            _make_post_response(post_id=1, title="First"),
            _make_post_response(post_id=2, title="Second"),
        ]
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=posts)
        )

        async with wp_client:
            results = await wp_client.list_posts(status="publish", per_page=10)

        assert len(results) == 2
        assert results[0].id == 1
        assert results[0].title.rendered == "First"
        assert results[1].id == 2
        assert results[1].title.rendered == "Second"

    @respx.mock
    async def test_list_posts_empty(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with wp_client:
            results = await wp_client.list_posts()

        assert results == []

    @respx.mock
    async def test_list_posts_sends_correct_params(self, wp_client: WordPressClient) -> None:
        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with wp_client:
            await wp_client.list_posts(status="draft", per_page=5, page=2)

        request = respx.calls.last.request
        assert request.url.params["status"] == "draft"
        assert request.url.params["per_page"] == "5"
        assert request.url.params["page"] == "2"
