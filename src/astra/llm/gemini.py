"""Google Gemini LLM provider (REST API v1beta)."""

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

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient(LLMClient):
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

    @llm_retry
    async def generate_content(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{_BASE_URL}/{self._model}:generateContent?key={self._api_key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": self._temperature,
                        "maxOutputTokens": self._max_tokens,
                    },
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
        raise LLMAuthError("Gemini: invalid API key")
    if resp.status_code == 429:
        raise LLMRateLimitError("Gemini: rate limited")
    if resp.status_code >= 500:
        raise LLMTransientError(f"Gemini: server error {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    return str(data["candidates"][0]["content"]["parts"][0]["text"])
