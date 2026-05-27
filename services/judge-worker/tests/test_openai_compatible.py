"""Provider client tests with mocked httpx — covers the request/response
shape of every OpenAI-wire-compatible client (OpenAI, Groq, xAI)."""

from __future__ import annotations

import json

import httpx
import pytest

from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient
from cascadia_judge.types import Message


def _completion_response(text: str = "hi") -> dict:
    return {
        "id": "chatcmpl-xxx",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


@pytest.mark.asyncio
async def test_openai_client_sends_bearer_and_parses_response() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_response("Paris."))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-test", client=mock_client)

    resp = await client.chat(system="be terse", messages=[Message(role="user", content="hi")])
    assert resp.text == "Paris."
    assert resp.model == "test-model"  # echoed back from the server
    assert resp.provider == "openai"
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 3
    assert captured["auth"] == "Bearer sk-test"
    payload = captured["payload"]
    assert payload["model"] == "gpt-4o-mini"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "be terse"
    assert payload["messages"][1]["role"] == "user"
    assert "api.openai.com" in str(captured["url"])


@pytest.mark.asyncio
async def test_openai_client_propagates_4xx() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-bad", client=mock_client)

    with pytest.raises(httpx.HTTPStatusError):
        await client.chat(system="x", messages=[Message(role="user", content="hi")])


def test_groq_client_uses_groq_base_url_and_provider() -> None:
    c = GroqClient(model="llama-3.3-70b", api_key="gsk-...")
    assert c.provider == "groq"
    assert "groq.com" in c._base_url


def test_xai_client_uses_xai_base_url_and_provider() -> None:
    c = XAIClient(model="grok-2", api_key="xai-...")
    assert c.provider == "xai"
    assert "x.ai" in c._base_url


@pytest.mark.asyncio
async def test_xai_client_chat_uses_correct_provider_tag() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response("ok"))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = XAIClient(model="grok-2", api_key="xai-key", client=mock_client)
    resp = await c.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.provider == "xai"


@pytest.mark.asyncio
async def test_groq_client_chat_uses_correct_provider_tag() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response("ok"))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c = GroqClient(model="llama-3.3-70b", api_key="gsk-key", client=mock_client)
    resp = await c.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.provider == "groq"


@pytest.mark.asyncio
async def test_openai_aclose_owns_client_when_default_constructed() -> None:
    # When no client is passed in, OpenAIClient owns the inner httpx client
    # and aclose() should close it.
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-x")
    assert client._owns_client is True
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_aclose_does_not_close_injected_client() -> None:
    mock = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-x", client=mock)
    assert client._owns_client is False
    await client.aclose()
    # The injected client is still usable.
    await mock.aclose()


@pytest.mark.asyncio
async def test_openai_client_tolerates_null_content() -> None:
    # A content-filter refusal / tool-only completion returns content: null.
    # Regression: this used to crash (None into the str field). Now it's "".
    resp_json = {
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": None},
                     "finish_reason": "content_filter"}],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=resp_json)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-x", client=mock_client)
    resp = await client.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.text == ""
    assert resp.finish_reason == "content_filter"


@pytest.mark.asyncio
async def test_openai_client_tolerates_empty_choices() -> None:
    # Some gateways return choices: [] on certain errors. Regression: this
    # used to raise IndexError. Now it yields an empty response.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "test-model", "choices": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAIClient(model="gpt-4o-mini", api_key="sk-x", client=mock_client)
    resp = await client.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.text == ""


def test_missing_api_key_raises() -> None:
    import os
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="missing API key"):
            OpenAIClient(model="gpt-4o-mini")
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
