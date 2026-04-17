"""Groq LLM provider (OpenAI-compatible API)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

import httpx

from astra.errors import LLMAuthError, LLMRateLimitError, LLMTransientError
from astra.llm._retry import llm_retry
from astra.llm.base import LLMClient

if TYPE_CHECKING:
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")

_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @llm_retry
    async def generate_content(self, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._model,
                    "temperature": self._temperature,
                    "max_tokens": self._max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
        return _handle_response(resp)

    @llm_retry
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        raw = await self.generate_content(system_prompt, user_prompt)
        return response_model.model_validate(json.loads(raw))


def _handle_response(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        raise LLMAuthError("Groq: invalid API key")
    if resp.status_code == 429:
        raise LLMRateLimitError("Groq: rate limited")
    if resp.status_code >= 500:
        raise LLMTransientError(f"Groq: server error {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    return str(data["choices"][0]["message"]["content"])
