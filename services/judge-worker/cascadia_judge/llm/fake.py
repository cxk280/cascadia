from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import LLMResponse, Message


@dataclass
class RecordedCall:
    system: str
    messages: list[Message]
    temperature: float
    max_tokens: int


class FakeLLMClient(LLMClient):
    provider = "fake"

    def __init__(
        self,
        model: str = "fake-model",
        responses: Iterable[str] | None = None,
    ) -> None:
        self.model = model
        self._responses: deque[str] = deque(responses or [])
        self.calls: list[RecordedCall] = []

    def queue(self, text: str) -> None:
        self._responses.append(text)

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.calls.append(
            RecordedCall(
                system=system,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        if not self._responses:
            raise RuntimeError("FakeLLMClient exhausted: queue another response")
        text = self._responses.popleft()
        return LLMResponse(text=text, model=self.model, provider=self.provider)
