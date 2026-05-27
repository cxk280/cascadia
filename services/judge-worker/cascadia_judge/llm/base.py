from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from cascadia_judge.types import LLMResponse, Message


class LLMClient(ABC):
    provider: str
    model: str

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...
