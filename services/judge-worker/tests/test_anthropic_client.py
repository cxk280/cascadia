"""AnthropicClient tests with mocked httpx.

Different wire format from OpenAI: `x-api-key` header, `system` as top-level
field, `content: [{type: "text", text: ...}]` array in responses.
"""

from __future__ import annotations

import json

import httpx
import pytest

from cascadia_judge.llm.anthropic import AnthropicClient
from cascadia_judge.types import Message


def _anthropic_response(text: str = "ok") -> dict:
    return {
        "id": "msg_xxx",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }


@pytest.mark.asyncio
async def test_anthropic_client_sends_x_api_key_and_parses_response() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["x_api_key"] = request.headers.get("x-api-key")
        captured["anthropic_version"] = request.headers.get("anthropic-version")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_anthropic_response("Paris."))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-ant-test", client=mock_client)
    resp = await client.chat(
        system="be terse", messages=[Message(role="user", content="capital of France?")],
    )
    assert resp.text == "Paris."
    assert resp.model == "claude-haiku-4-5"
    assert resp.provider == "anthropic"
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 4
    assert resp.finish_reason == "end_turn"
    assert captured["x_api_key"] == "sk-ant-test"
    assert captured["anthropic_version"] == AnthropicClient.ANTHROPIC_VERSION
    payload = captured["payload"]
    # Anthropic uses a top-level `system` field, NOT a system message in the
    # messages list — this is the load-bearing format difference from OpenAI.
    assert payload["system"] == "be terse"
    assert payload["messages"] == [{"role": "user", "content": "capital of France?", "name": None, "extra": {}}] or \
           payload["messages"][0]["role"] == "user"
    assert payload["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_anthropic_client_concatenates_multi_part_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "content": [
                {"type": "text", "text": "part one. "},
                {"type": "text", "text": "part two."},
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-x", client=mock_client)
    resp = await client.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.text == "part one. part two."


@pytest.mark.asyncio
async def test_anthropic_client_skips_non_text_content_blocks() -> None:
    # If Anthropic returns a non-text block (e.g. tool_use), the chat shim
    # should silently skip it for `.text` purposes.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "foo", "input": {}},
                {"type": "text", "text": "just this."},
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-x", client=mock_client)
    resp = await client.chat(system="x", messages=[Message(role="user", content="hi")])
    assert resp.text == "just this."


@pytest.mark.asyncio
async def test_anthropic_client_propagates_4xx() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "authentication_error"}})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-bad", client=mock_client)
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat(system="x", messages=[Message(role="user", content="hi")])


def test_anthropic_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="missing API key"):
        AnthropicClient(model="claude-haiku-4-5")


@pytest.mark.asyncio
async def test_anthropic_aclose_owns_default_client() -> None:
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-x")
    assert client._owns_client is True
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_aclose_skips_injected_client() -> None:
    mock = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client = AnthropicClient(model="claude-haiku-4-5", api_key="sk-x", client=mock)
    assert client._owns_client is False
    await client.aclose()
    await mock.aclose()
