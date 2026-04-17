"""LLM provider unit tests.

Gate (phase 4):
- respx mocks for each provider: happy path, 401, 429, 5xx-then-success.
- Two-tenant test: tenant A with custom api_key_env does not use operator key.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response
from pydantic import BaseModel

from astra.config.models import LLMConfig
from astra.errors import LLMAuthError, LLMRateLimitError, LLMTransientError
from astra.llm.factory import build_llm_client


def _cfg(provider: str) -> LLMConfig:
    return LLMConfig(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        temperature=0.7,
        max_tokens=512,
    )


# ── helpers ──────────────────────────────────────────────────────

class _Reply(BaseModel):
    text: str


# ── OpenAI ───────────────────────────────────────────────────────

class TestOpenAI:
    _URL = "https://api.openai.com/v1/chat/completions"

    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post(self._URL).mock(
            return_value=Response(
                200,
                json={"choices": [{"message": {"content": "Hello!"}}]},
            )
        )
        client = build_llm_client(_cfg("openai"), api_key="sk-test")
        result = await client.generate_content("sys", "user")
        assert result == "Hello!"

    @respx.mock
    async def test_401_raises_auth_error(self) -> None:
        respx.post(self._URL).mock(return_value=Response(401, json={"error": "bad key"}))
        client = build_llm_client(_cfg("openai"), api_key="bad")
        with pytest.raises(LLMAuthError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_429_raises_rate_limit(self) -> None:
        respx.post(self._URL).mock(return_value=Response(429, json={}))
        client = build_llm_client(_cfg("openai"), api_key="k")
        with pytest.raises(LLMRateLimitError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_5xx_then_success(self) -> None:
        respx.post(self._URL).mock(
            side_effect=[
                Response(503, json={}),
                Response(503, json={}),
                Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
            ]
        )
        client = build_llm_client(_cfg("openai"), api_key="k")
        result = await client.generate_content("s", "u")
        assert result == "ok"

    @respx.mock
    async def test_three_5xx_raises_transient(self) -> None:
        respx.post(self._URL).mock(return_value=Response(503, json={}))
        client = build_llm_client(_cfg("openai"), api_key="k")
        with pytest.raises(LLMTransientError):
            await client.generate_content("s", "u")


# ── Anthropic ────────────────────────────────────────────────────

class TestAnthropic:
    _URL = "https://api.anthropic.com/v1/messages"

    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post(self._URL).mock(
            return_value=Response(
                200,
                json={"content": [{"text": "Claude here"}]},
            )
        )
        client = build_llm_client(_cfg("anthropic"), api_key="sk-ant-test")
        result = await client.generate_content("sys", "user")
        assert result == "Claude here"

    @respx.mock
    async def test_401_raises_auth_error(self) -> None:
        respx.post(self._URL).mock(return_value=Response(401, json={}))
        client = build_llm_client(_cfg("anthropic"), api_key="bad")
        with pytest.raises(LLMAuthError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_429_raises_rate_limit(self) -> None:
        respx.post(self._URL).mock(return_value=Response(429, json={}))
        client = build_llm_client(_cfg("anthropic"), api_key="k")
        with pytest.raises(LLMRateLimitError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_5xx_then_success(self) -> None:
        respx.post(self._URL).mock(
            side_effect=[
                Response(500, json={}),
                Response(200, json={"content": [{"text": "retry worked"}]}),
            ]
        )
        client = build_llm_client(_cfg("anthropic"), api_key="k")
        result = await client.generate_content("s", "u")
        assert result == "retry worked"


# ── Groq ─────────────────────────────────────────────────────────

class TestGroq:
    _URL = "https://api.groq.com/openai/v1/chat/completions"

    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post(self._URL).mock(
            return_value=Response(
                200,
                json={"choices": [{"message": {"content": "Groq says hi"}}]},
            )
        )
        client = build_llm_client(_cfg("groq"), api_key="gsk-test")
        result = await client.generate_content("sys", "user")
        assert result == "Groq says hi"

    @respx.mock
    async def test_401_raises_auth_error(self) -> None:
        respx.post(self._URL).mock(return_value=Response(401, json={}))
        client = build_llm_client(_cfg("groq"), api_key="bad")
        with pytest.raises(LLMAuthError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_429_raises_rate_limit(self) -> None:
        respx.post(self._URL).mock(return_value=Response(429, json={}))
        client = build_llm_client(_cfg("groq"), api_key="k")
        with pytest.raises(LLMRateLimitError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_5xx_then_success(self) -> None:
        respx.post(self._URL).mock(
            side_effect=[
                Response(502, json={}),
                Response(200, json={"choices": [{"message": {"content": "done"}}]}),
            ]
        )
        client = build_llm_client(_cfg("groq"), api_key="k")
        result = await client.generate_content("s", "u")
        assert result == "done"


# ── Gemini ───────────────────────────────────────────────────────

class TestGemini:
    _URL_PATTERN = "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"

    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post(url__startswith=self._URL_PATTERN).mock(
            return_value=Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "Gemini reply"}]}}]},
            )
        )
        client = build_llm_client(_cfg("gemini"), api_key="AIza-test")
        result = await client.generate_content("sys", "user")
        assert result == "Gemini reply"

    @respx.mock
    async def test_401_raises_auth_error(self) -> None:
        respx.post(url__startswith=self._URL_PATTERN).mock(
            return_value=Response(401, json={})
        )
        client = build_llm_client(_cfg("gemini"), api_key="bad")
        with pytest.raises(LLMAuthError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_429_raises_rate_limit(self) -> None:
        respx.post(url__startswith=self._URL_PATTERN).mock(
            return_value=Response(429, json={})
        )
        client = build_llm_client(_cfg("gemini"), api_key="k")
        with pytest.raises(LLMRateLimitError):
            await client.generate_content("s", "u")

    @respx.mock
    async def test_5xx_then_success(self) -> None:
        respx.post(url__startswith=self._URL_PATTERN).mock(
            side_effect=[
                Response(503, json={}),
                Response(
                    200,
                    json={"candidates": [{"content": {"parts": [{"text": "retry ok"}]}}]},
                ),
            ]
        )
        client = build_llm_client(_cfg("gemini"), api_key="k")
        result = await client.generate_content("s", "u")
        assert result == "retry ok"


# ── Factory / two-tenant isolation ───────────────────────────────

def test_factory_unknown_provider_raises() -> None:
    from astra.errors import LLMError

    # Use model_construct to bypass pydantic validation so the factory's
    # safety net is exercised directly.
    bad_cfg = LLMConfig.model_construct(
        provider="fake_provider",
        model="m",
        temperature=0.7,
        max_tokens=512,
    )
    with pytest.raises(LLMError, match="Unknown LLM provider"):
        build_llm_client(bad_cfg, api_key="x")


@respx.mock
async def test_two_tenants_use_different_api_keys() -> None:
    """Tenant A's key must not bleed into tenant B's client (P5)."""

    _URL = "https://api.openai.com/v1/chat/completions"
    captured: list[str] = []

    def _capture(request: respx.models.Request, route: respx.models.Route) -> Response:
        auth = request.headers.get("authorization", "")
        captured.append(auth)
        return Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    respx.post(_URL).mock(side_effect=_capture)

    client_a = build_llm_client(_cfg("openai"), api_key="key-for-tenant-a")
    client_b = build_llm_client(_cfg("openai"), api_key="key-for-tenant-b")
    await client_a.generate_content("s", "u")
    await client_b.generate_content("s", "u")

    assert "key-for-tenant-a" in captured[0]
    assert "key-for-tenant-b" in captured[1]
    assert "key-for-tenant-a" not in captured[1]
