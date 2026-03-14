from __future__ import annotations

import pytest
from pydantic import BaseModel

from astra.llm.base import LLMClient
from astra.llm.factory import create_llm_client
from tests.conftest import MockLLMClient

# ── Structured response model for testing ────────────────────────


class SampleResponse(BaseModel):
    name: str
    score: int


# ── Factory tests ────────────────────────────────────────────────


class TestLLMFactory:
    """Test create_llm_client returns correct client types."""

    def test_factory_returns_openai_client(self) -> None:
        client = create_llm_client(provider="openai", api_key="sk-test", model="gpt-4o")
        from astra.llm.openai_client import OpenAIClient

        assert isinstance(client, OpenAIClient)

    def test_factory_returns_anthropic_client(self) -> None:
        client = create_llm_client(
            provider="anthropic", api_key="sk-ant",
            model="claude-sonnet-4-20250514",
        )
        from astra.llm.anthropic_client import AnthropicClient

        assert isinstance(client, AnthropicClient)

    def test_factory_case_insensitive(self) -> None:
        client = create_llm_client(provider="  OpenAI  ", api_key="sk-test", model="gpt-4o")
        from astra.llm.openai_client import OpenAIClient

        assert isinstance(client, OpenAIClient)

    def test_factory_raises_for_unknown_provider(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_client(provider="google", api_key="key", model="gemini")

    def test_factory_raises_for_empty_provider(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_client(provider="", api_key="key", model="model")


# ── Mock LLM client tests ───────────────────────────────────────


class TestMockLLMClient:
    """Test that MockLLMClient satisfies the LLMClient interface."""

    def test_mock_is_subclass_of_llm_client(self) -> None:
        assert issubclass(MockLLMClient, LLMClient)

    async def test_generate_content_returns_text(self, mock_llm_client: MockLLMClient) -> None:
        result = await mock_llm_client.generate_content("Write something")
        assert result == "Mock generated content."

    async def test_generate_content_custom_response(self) -> None:
        client = MockLLMClient(text_response="Custom text output")
        result = await client.generate_content("Any prompt")
        assert result == "Custom text output"

    async def test_generate_content_records_calls(self, mock_llm_client: MockLLMClient) -> None:
        await mock_llm_client.generate_content(
            "prompt text", system_prompt="system", temperature=0.5, max_tokens=100
        )
        assert len(mock_llm_client.generate_content_calls) == 1
        call = mock_llm_client.generate_content_calls[0]
        assert call["prompt"] == "prompt text"
        assert call["system_prompt"] == "system"
        assert call["temperature"] == 0.5
        assert call["max_tokens"] == 100

    async def test_generate_structured_returns_model(self, mock_llm_client: MockLLMClient) -> None:
        client = MockLLMClient(structured_response={"name": "test", "score": 95})
        result = await client.generate_structured("prompt", SampleResponse)
        assert isinstance(result, SampleResponse)
        assert result.name == "test"
        assert result.score == 95

    async def test_generate_structured_records_calls(
        self, mock_llm_client: MockLLMClient
    ) -> None:
        client = MockLLMClient(structured_response={"name": "a", "score": 1})
        await client.generate_structured("p", SampleResponse, system_prompt="sys")
        assert len(client.generate_structured_calls) == 1
        call = client.generate_structured_calls[0]
        assert call["prompt"] == "p"
        assert call["response_model"] is SampleResponse
        assert call["system_prompt"] == "sys"

    async def test_generate_structured_with_default_response(
        self, mock_llm_client: MockLLMClient
    ) -> None:
        """The default structured_response matches GeneratedPost shape."""
        from astra.core.engine import GeneratedPost

        result = await mock_llm_client.generate_structured("p", GeneratedPost)
        assert isinstance(result, GeneratedPost)
        assert result.title == "Test Post Title"
        assert len(result.tags) == 2
