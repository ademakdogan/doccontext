from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from doccontext.config import Settings
from doccontext.llm.base import Message
from doccontext.llm.openrouter import OpenRouterClient, OpenRouterError


def _settings() -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        openrouter_base_url="https://openrouter.test/api/v1",
        llm_answer_model="openai/gpt-5-mini",
        llm_router_model="openai/gpt-5-mini",
    )


def _make_client(handler) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return OpenRouterClient(_settings(), http_client=http)


def _ok_payload(content: str = "hello") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "model": "openai/gpt-5-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


async def test_complete_sends_request_and_parses_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload("the answer is 42"))

    client = _make_client(handler)
    try:
        resp = await client.complete(
            [Message(role="user", content="q")],
            model="openai/gpt-5-mini",
            temperature=0.2,
        )
    finally:
        await client.aclose()

    assert captured["url"] == "https://openrouter.test/api/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "openai/gpt-5-mini"
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["messages"] == [{"role": "user", "content": "q"}]

    assert resp.content == "the answer is 42"
    assert resp.model == "openai/gpt-5-mini"
    assert resp.usage.prompt_tokens == 5
    assert resp.usage.completion_tokens == 3
    assert resp.usage.total_tokens == 8


async def test_complete_forwards_response_format() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload())

    client = _make_client(handler)
    try:
        await client.complete(
            [Message(role="user", content="q")],
            model="openai/gpt-5-mini",
            response_format={"type": "json_object"},
        )
    finally:
        await client.aclose()

    assert captured["body"]["response_format"] == {"type": "json_object"}


async def test_complete_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    client = _make_client(handler)
    try:
        with pytest.raises(OpenRouterError) as ei:
            await client.complete(
                [Message(role="user", content="q")], model="openai/gpt-5-mini"
            )
    finally:
        await client.aclose()
    assert "500" in str(ei.value)


async def test_complete_raises_on_missing_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [], "usage": {}})

    client = _make_client(handler)
    try:
        with pytest.raises(OpenRouterError):
            await client.complete(
                [Message(role="user", content="q")], model="openai/gpt-5-mini"
            )
    finally:
        await client.aclose()


async def test_complete_raises_on_missing_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant"}}],
                "usage": {},
            },
        )

    client = _make_client(handler)
    try:
        with pytest.raises(OpenRouterError):
            await client.complete(
                [Message(role="user", content="q")], model="openai/gpt-5-mini"
            )
    finally:
        await client.aclose()


async def test_aclose_does_not_close_externally_owned_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload())

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = OpenRouterClient(_settings(), http_client=http)
    await client.aclose()
    assert not http.is_closed  # caller still owns it
    await http.aclose()
