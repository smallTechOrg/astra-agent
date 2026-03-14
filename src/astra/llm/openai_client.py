from __future__ import annotations

import json
from typing import TypeVar

import structlog
from openai import APIStatusError, AsyncOpenAI, RateLimitError
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

# Retry decorator for transient / rate-limit errors.
_retry_policy = retry(
    retry=retry_if_exception_type((APIStatusError, RateLimitError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=60),
    reraise=True,
)


class OpenAIClient(LLMClient):
    """OpenAI-backed LLM client using the official async SDK."""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._log = logger.bind(provider="openai", model=model)

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
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        self._log.debug(
            "openai.generate_content",
            prompt_len=len(prompt),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or ""
        self._log.debug(
            "openai.generate_content.complete",
            response_len=len(text),
            usage=response.usage.model_dump() if response.usage else None,
        )
        return text

    # ------------------------------------------------------------------
    # Structured (JSON-mode) generation
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
            "Return ONLY the JSON object — no commentary, no markdown fences."
        )

        messages: list[dict[str, str]] = []
        if system_prompt:
            combined = f"{system_prompt}\n\n{schema_instruction}"
            messages.append({"role": "system", "content": combined})
        else:
            messages.append({"role": "system", "content": schema_instruction})
        messages.append({"role": "user", "content": prompt})

        self._log.debug(
            "openai.generate_structured",
            prompt_len=len(prompt),
            response_model=response_model.__name__,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        self._log.debug(
            "openai.generate_structured.complete",
            raw_len=len(raw),
            usage=response.usage.model_dump() if response.usage else None,
        )
        return response_model.model_validate_json(raw)
