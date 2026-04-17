"""LLM client factory.

Keyed on operator.yaml llm.provider. Per-tenant api_key_env override is
resolved by the caller (secrets are injected as plain strings, not stored
on module state — P5, spec/engineering/tenant-isolation.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.errors import LLMError

if TYPE_CHECKING:
    from astra.config.models import LLMConfig
    from astra.llm.base import LLMClient


def build_llm_client(cfg: LLMConfig, *, api_key: str) -> LLMClient:
    """Construct the correct provider client from *cfg*.

    *api_key* is the already-resolved secret (caller handles precedence).
    """

    provider = cfg.provider
    kwargs = {
        "api_key": api_key,
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }

    if provider == "openai":
        from astra.llm.openai import OpenAIClient
        return OpenAIClient(**kwargs)  # type: ignore[arg-type]
    if provider == "anthropic":
        from astra.llm.anthropic import AnthropicClient
        return AnthropicClient(**kwargs)  # type: ignore[arg-type]
    if provider == "groq":
        from astra.llm.groq import GroqClient
        return GroqClient(**kwargs)  # type: ignore[arg-type]
    if provider == "gemini":
        from astra.llm.gemini import GeminiClient
        return GeminiClient(**kwargs)  # type: ignore[arg-type]

    raise LLMError(f"Unknown LLM provider: {provider!r}")
