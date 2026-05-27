from __future__ import annotations

import os
from collections.abc import Sequence

import httpx

from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import LLMResponse, Message


class AnthropicClient(LLMClient):
    BASE_URL = "https://api.anthropic.com/v1"
    API_KEY_ENV = "ANTHROPIC_API_KEY"
    ANTHROPIC_VERSION = "2023-06-01"
    provider = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url or self.BASE_URL
        self._api_key = api_key or os.environ.get(self.API_KEY_ENV)
        if not self._api_key:
            raise RuntimeError(f"missing API key (set {self.API_KEY_ENV})")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "system": system,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        resp = await self._client.post(
            f"{self._base_url}/messages",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        usage = data.get("usage") or {}
        return LLMResponse(
            text="".join(text_parts),
            model=data.get("model", self.model),
            provider=self.provider,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
        )
