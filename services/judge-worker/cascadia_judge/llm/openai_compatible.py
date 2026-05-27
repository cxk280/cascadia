from __future__ import annotations

import os
from collections.abc import Sequence
from typing import ClassVar

import httpx

from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import LLMResponse, Message


class _OpenAICompatibleClient(LLMClient):
    BASE_URL: ClassVar[str]
    API_KEY_ENV: ClassVar[str]
    provider: ClassVar[str]

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
            "messages": [
                {"role": "system", "content": system},
                *[m.model_dump() for m in messages],
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        # Tolerate empty `choices` and null `content`. A content-filter
        # refusal or a tool/function-call-only completion returns
        # `content: null`, and some gateways return `choices: []` on certain
        # errors. Crashing here (IndexError / None into the str field) turned
        # those into a hard error verdict; normalize to "" like the Anthropic
        # client so the judge treats it as an empty response instead.
        choices = data.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", self.model),
            provider=self.provider,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )


class OpenAIClient(_OpenAICompatibleClient):
    BASE_URL = "https://api.openai.com/v1"
    API_KEY_ENV = "OPENAI_API_KEY"
    provider = "openai"


class GroqClient(_OpenAICompatibleClient):
    BASE_URL = "https://api.groq.com/openai/v1"
    API_KEY_ENV = "GROQ_API_KEY"
    provider = "groq"


class XAIClient(_OpenAICompatibleClient):
    BASE_URL = "https://api.x.ai/v1"
    API_KEY_ENV = "XAI_API_KEY"
    provider = "xai"
