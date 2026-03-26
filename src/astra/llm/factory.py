from __future__ import annotations

from astra.llm.base import LLMClient


def create_llm_client(provider: str, api_key: str, model: str) -> LLMClient:
    """Instantiate the appropriate :class:`LLMClient` for *provider*.

    Args:
        provider: One of ``"openai"`` or ``"anthropic"`` (case-insensitive).
        api_key: The API key for the chosen provider.
        model: The model identifier (e.g. ``"gpt-4o"``, ``"claude-sonnet-4-20250514"``).

    Returns:
        A configured :class:`LLMClient` instance.

    Raises:
        ValueError: If *provider* is not recognised.
    """
    provider_lower = provider.lower().strip()

    if provider_lower == "openai":
        from astra.llm.openai_client import OpenAIClient

        return OpenAIClient(api_key=api_key, model=model)

    if provider_lower == "anthropic":
        from astra.llm.anthropic_client import AnthropicClient

        return AnthropicClient(api_key=api_key, model=model)

    if provider_lower == "groq":
        from astra.llm.groq_client import GroqClient

        return GroqClient(api_key=api_key, model=model)

    supported = ("openai", "anthropic", "groq")
    msg = f"Unknown LLM provider {provider!r}. Supported providers: {supported}"
    raise ValueError(msg)
