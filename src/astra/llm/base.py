"""Abstract LLMClient interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")


class LLMClient(ABC):
    """Single-method LLM abstraction.

    Concrete impls live in provider-specific modules; factory in factory.py.
    The api_key is injected at construction time (P5 — never stored on
    module-level globals).
    """

    @abstractmethod
    async def generate_content(self, system_prompt: str, user_prompt: str) -> str:
        """Return the raw text output from the model."""
        ...

    @abstractmethod
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Return a Pydantic model instance parsed from the model's JSON output."""
        ...
