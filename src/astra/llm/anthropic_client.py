from __future__ import annotations

import json
from typing import TypeVar

import structlog
from anthropic import APIStatusError, AsyncAnthropic, RateLimitError
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from astra.llm.base import LLMClient

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_retry_policy = retry(
    retry=retry_if_exception_type((APIStatusError, RateLimitError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=60),
    reraise=True,
)


class AnthropicClient(LLMClient):
    """Anthropic-backed LLM client using the official async SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._log = logger.bind(provider="anthropic", model=model)

    # ------------------------------------------------------------------
    # Plain-text generation
    # ------------------------------------------------------------------

    @_retry_policy
    async def generate_content(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        self._log.debug(
            "anthropic.generate_content",
            prompt_len=len(prompt),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)  # type: ignore[arg-type]

        text = response.content[0].text  # type: ignore[union-attr]
        self._log.debug(
            "anthropic.generate_content.complete",
            response_len=len(text),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return text

    # ------------------------------------------------------------------
    # Structured generation
    # ------------------------------------------------------------------

    @_retry_policy
    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        *,
        system_prompt: str | None = None,
    ) -> T:
        schema = response_model.model_json_schema()
        schema_instruction = (
            "You MUST respond with valid JSON that conforms to the following "
            f"JSON schema:\n\n```json\n{json.dumps(schema, indent=2)}\n```\n\n"
            "Return ONLY the raw JSON object — no commentary, no markdown fences."
        )

        system = schema_instruction
        if system_prompt:
            system = f"{system_prompt}\n\n{schema_instruction}"

        self._log.debug(
            "anthropic.generate_structured",
            prompt_len=len(prompt),
            response_model=response_model.__name__,
        )

        response = await self._client.messages.create(
            model=self._model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4000,
        )

        raw = response.content[0].text  # type: ignore[union-attr]
        self._log.debug(
            "anthropic.generate_structured.complete",
            raw_len=len(raw),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return response_model.model_validate_json(raw)
