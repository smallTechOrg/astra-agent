"""LLM client abstraction.

Per spec/product/02-architecture.md#llmclient and spec/product/09-extensibility.md:
abstract LLMClient + four concrete providers, factory keyed on operator_config.llm_provider.
Per-tenant api_key_env override is passed as a resolved secret, not stored on module state (P5).
"""

from __future__ import annotations

from astra.llm.base import LLMClient
from astra.llm.factory import build_llm_client

__all__ = ["LLMClient", "build_llm_client"]
