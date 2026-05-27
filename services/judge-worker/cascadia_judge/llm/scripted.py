from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import LLMResponse, Message


class ScriptedLLMClient(LLMClient):
    """Replays LLM responses from a JSON fixture keyed by (judge_name, request_id).

    Fixture shape:
        {
          "model": "scripted-model",
          "responses": {
            "<judge_name>::<request_id>": "raw response text",
            ...
          }
        }

    Same `LLMClient` contract as live providers — CI tests run offline with no
    keys; fallback for stage demos with bad WiFi.
    """

    provider = "scripted"

    def __init__(self, fixture: dict[str, Any] | str | Path) -> None:
        if isinstance(fixture, (str, Path)):
            fixture = json.loads(Path(fixture).read_text())
        self.model = fixture.get("model", "scripted-model")
        self._responses: dict[str, str] = dict(fixture.get("responses", {}))
        self._pending_key: str | None = None
        self.misses: list[str] = []

    def bind(self, judge_name: str, request_id: str) -> None:
        self._pending_key = f"{judge_name}::{request_id}"

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        key = self._pending_key
        if key is None:
            raise RuntimeError("ScriptedLLMClient.bind(judge_name, request_id) must be called first")
        self._pending_key = None
        if key not in self._responses:
            self.misses.append(key)
            raise KeyError(f"no scripted response for key {key!r}")
        return LLMResponse(
            text=self._responses[key],
            model=self.model,
            provider=self.provider,
        )
