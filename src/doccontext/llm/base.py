from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "system", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """Chat-style message. Role mirrors the OpenAI / OpenRouter schema."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(abc.ABC):
    """Provider-agnostic chat completion client."""

    @abc.abstractmethod
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Run a chat completion and return the assistant's reply."""

    async def aclose(self) -> None:
        """Release any transport resources. Override if needed."""
