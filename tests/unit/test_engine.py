from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from astra.config import AstraConfig
from astra.core.engine import AstraEngine, GeneratedPost
from astra.wordpress.models import ContentBrief
from tests.conftest import MockLLMClient

BASE_URL = "http://wp.test.local"
API_URL = f"{BASE_URL}/wp-json/wp/v2"


def _make_wp_response(
    post_id: int = 1,
    title: str = "Test Post Title",
    status: str = "draft",
) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": post_id,
        "link": f"{BASE_URL}/?p={post_id}",
        "status": status,
        "date": now,
        "title": {"rendered": title},
        "modified": now,
    }


@pytest.fixture()
def engine_config(tmp_path: Path) -> AstraConfig:
    return AstraConfig(
        llm={"provider": "openai", "model": "gpt-4o", "api_key": "sk-test-key"},
        wordpress={"url": BASE_URL, "username": "testuser", "app_password": "testpass"},
        twitter={"bearer_token": ""},  # No social clients
        linkedin={"access_token": ""},
        database_path=str(tmp_path / "engine_test.db"),
        _env_file=None,
    )


class TestGeneratePostDryRun:
    """Test engine.generate_post in dry_run mode (no WordPress calls)."""

    @respx.mock
    async def test_dry_run_returns_dict(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                result = await engine.generate_post(content_brief, dry_run=True)

        assert isinstance(result, dict)
        assert result["title"] == "Test Post Title"
        assert result["content"] == "<p>Test post body content.</p>"
        assert result["excerpt"] == "A short test excerpt."
        assert result["tags"] == ["python", "testing"]
        assert result["status"] == "draft"

    @respx.mock
    async def test_dry_run_does_not_call_wordpress_create(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )
        create_route = respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=_make_wp_response())
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                await engine.generate_post(content_brief, dry_run=True)

        assert not create_route.called

    @respx.mock
    async def test_dry_run_publish_flag_reflected_in_status(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                result = await engine.generate_post(
                    content_brief, dry_run=True, publish=True
                )

        assert result["status"] == "publish"

    @respx.mock
    async def test_dry_run_calls_llm_with_brief_details(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                await engine.generate_post(content_brief, dry_run=True)

        assert len(mock_llm.generate_structured_calls) == 1
        call = mock_llm.generate_structured_calls[0]
        assert call["response_model"] is GeneratedPost
        assert content_brief.topic in call["prompt"]
        assert call["system_prompt"] is not None


class TestGeneratePostPublish:
    """Test engine.generate_post in publish mode (mock both LLM and WordPress)."""

    @respx.mock
    async def test_publish_mode_creates_post_on_wordpress(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )
        wp_response = _make_wp_response(post_id=55, title="Test Post Title", status="publish")
        create_route = respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=wp_response)
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                result = await engine.generate_post(
                    content_brief, publish=True, dry_run=False
                )

        assert create_route.called
        assert result.id == 55
        assert result.status == "publish"

    @respx.mock
    async def test_publish_mode_records_post_in_database(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )
        wp_response = _make_wp_response(post_id=77, title="Test Post Title", status="draft")
        respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=wp_response)
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                await engine.generate_post(content_brief, publish=False)
                db_record = await engine._db.get_post_by_wp_id(77)

        assert db_record is not None
        assert db_record.title == "Test Post Title"
        assert db_record.wp_post_id == 77

    @respx.mock
    async def test_publish_mode_sends_correct_payload(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )
        respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=_make_wp_response(post_id=88))
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                await engine.generate_post(content_brief, publish=True)

        import json

        request = respx.calls.last.request
        body = json.loads(request.content)
        assert body["title"] == "Test Post Title"
        assert body["content"] == "<p>Test post body content.</p>"
        assert body["status"] == "publish"
        assert body["excerpt"] == "A short test excerpt."

    @respx.mock
    async def test_draft_mode_uses_draft_status(
        self, engine_config: AstraConfig, content_brief: ContentBrief
    ) -> None:
        mock_llm = MockLLMClient()

        respx.get(f"{API_URL}/posts").mock(
            return_value=httpx.Response(200, json=[_make_wp_response()])
        )
        respx.post(f"{API_URL}/posts").mock(
            return_value=httpx.Response(201, json=_make_wp_response(post_id=99, status="draft"))
        )

        with patch("astra.core.engine.create_llm_client", return_value=mock_llm):
            async with AstraEngine(engine_config) as engine:
                result = await engine.generate_post(content_brief, publish=False)

        assert result.status == "draft"

        import json

        request = respx.calls.last.request
        body = json.loads(request.content)
        assert body["status"] == "draft"
