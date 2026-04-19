"""Shared tenacity retry decorator for LLM providers.

Retries on transient 5xx / connection errors; never on 4xx.
spec/engineering/code-style.md: use tenacity with wait_exponential + stop_after_attempt.
"""

from __future__ import annotations

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from astra.errors import LLMTransientError

llm_retry = retry(
    retry=retry_if_exception_type(LLMTransientError),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
