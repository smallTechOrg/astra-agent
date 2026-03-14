from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Abstract base class for LLM provider clients.

    All implementations must provide async methods for plain-text generation
    and Pydantic-model-validated structured output.
    """

    @abstractmethod
    async def generate_content(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        """Generate plain-text content from a prompt.

        Args:
            prompt: The user-facing prompt text.
            system_prompt: Optional system-level instruction.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.

        Returns:
            The generated text content.
        """

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        *,
        system_prompt: str | None = None,
    ) -> T:
        """Generate a response and parse it into a Pydantic model.

        The implementation should instruct the model to return valid JSON that
        conforms to ``response_model``'s schema, then validate the output.

        Args:
            prompt: The user-facing prompt text.
            response_model: A Pydantic ``BaseModel`` subclass describing the
                expected response shape.
            system_prompt: Optional system-level instruction.

        Returns:
            A validated instance of ``response_model``.
        """
