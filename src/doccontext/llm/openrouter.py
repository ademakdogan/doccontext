from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from doccontext.config import Settings, get_settings
from doccontext.llm.base import LLMClient, LLMResponse, Message, Usage


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns a non-2xx response or malformed JSON."""


class OpenRouterClient(LLMClient):
    """Chat-completion client backed by OpenRouter's /chat/completions endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        s = settings or get_settings()
        self._settings = s
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._endpoint = f"{s.openrouter_base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {s.openrouter_api_key}",
            "Content-Type": "application/json",
            # OpenRouter recommends these for analytics but does not require them.
            "HTTP-Referer": "https://github.com/doccontext",
            "X-Title": "doccontext",
        }

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if response_format is not None:
            body["response_format"] = response_format

        try:
            resp = await self._http.post(
                self._endpoint, headers=self._headers, json=body
            )
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"HTTP error calling OpenRouter: {exc}") from exc

        if resp.status_code >= 400:
            raise OpenRouterError(
                f"OpenRouter returned {resp.status_code}: {resp.text[:500]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise OpenRouterError(f"OpenRouter returned non-JSON body: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError(f"OpenRouter response had no choices: {data}")
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise OpenRouterError(f"OpenRouter response missing content: {data}")

        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
        )
        return LLMResponse(
            content=content,
            model=str(data.get("model", model)),
            usage=usage,
            raw=data,
        )

    async def aclose(self) -> None:
        if self._owns_client and not self._http.is_closed:
            await self._http.aclose()
