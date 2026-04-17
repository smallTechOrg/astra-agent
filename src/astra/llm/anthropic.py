"""Anthropic (Claude) LLM provider."""

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

_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClient(LLMClient):
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
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    @llm_retry
    async def generate_content(self, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE_URL}/messages",
                headers=self._headers(),
                json={
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "temperature": self._temperature,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
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
        raise LLMAuthError("Anthropic: invalid API key")
    if resp.status_code == 429:
        raise LLMRateLimitError("Anthropic: rate limited")
    if resp.status_code >= 500:
        raise LLMTransientError(f"Anthropic: server error {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    return str(data["content"][0]["text"])
