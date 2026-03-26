from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from astra.config import AstraConfig
from astra.llm.base import LLMClient
from astra.wordpress.models import ContentBrief

T = TypeVar("T", bound=BaseModel)


# ── Mock LLM client ──────────────────────────────────────────────


class MockLLMClient(LLMClient):
    """Concrete mock LLM client that returns predetermined responses.

    Configure via ``text_response`` for ``generate_content`` and
    ``structured_response`` (a dict) for ``generate_structured``.
    """

    def __init__(
        self,
        text_response: str = "Mock generated content.",
        structured_response: dict | None = None,
    ) -> None:
        self.text_response = text_response
        self.structured_response = structured_response or {
            "title": "Test Post Title",
            "content": "<p>Test post body content.</p>",
            "excerpt": "A short test excerpt.",
            "tags": ["python", "testing"],
        }
        # Track calls for assertions
        self.generate_content_calls: list[dict] = []
        self.generate_structured_calls: list[dict] = []

    async def generate_content(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        self.generate_content_calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.text_response

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        *,
        system_prompt: str | None = None,
    ) -> T:
        self.generate_structured_calls.append(
            {
                "prompt": prompt,
                "response_model": response_model,
                "system_prompt": system_prompt,
            }
        )
        return response_model.model_validate_json(json.dumps(self.structured_response))


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def sample_config(tmp_path: Path) -> AstraConfig:
    """AstraConfig with safe test values (no real API keys)."""
    return AstraConfig(
        llm={"provider": "openai", "model": "gpt-4o-test", "api_key": "sk-test-fake-key-000"},
        wordpress={
            "url": "http://wp.test.local",
            "username": "testuser",
            "app_password": "test-app-pw",
        },
        twitter={"api_key": "tw-key", "api_secret": "tw-secret"},
        linkedin={"access_token": "li-token", "organization_id": "li-org-123"},
        database_path=str(tmp_path / "test_astra.db"),
        log_level="debug",
        _env_file=None,
    )


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Temporary file path for a SQLite database."""
    return tmp_path / "astra_test.db"


@pytest.fixture()
def content_brief() -> ContentBrief:
    """Sample ContentBrief for testing."""
    return ContentBrief(
        topic="Best Practices for Python Testing",
        tone="informative",
        target_word_count=1200,
        keywords=["pytest", "testing", "python"],
        categories=["Engineering"],
        tags=["python", "testing"],
    )


@pytest.fixture()
def mock_llm_client() -> MockLLMClient:
    """A MockLLMClient instance with default responses."""
    return MockLLMClient()
