from __future__ import annotations

import pytest

from doccontext.config import Settings
from doccontext.llm.base import Message
from doccontext.llm.openrouter import OpenRouterClient

pytestmark = pytest.mark.integration


async def test_openrouter_live_round_trip() -> None:
    """One real call against OpenRouter to prove the wire contract.

    Skipped unless OPENROUTER_API_KEY is set via the project .env.
    """
    settings = Settings()
    if not settings.openrouter_api_key:
        pytest.skip("OPENROUTER_API_KEY is empty — set it in .env to run this test")

    client = OpenRouterClient(settings)
    try:
        resp = await client.complete(
            [
                Message(
                    role="user",
                    content="Reply with exactly the single word: pong",
                ),
                Message(
                    role="system",
                    content="Respond with one lowercase word and nothing else.",
                ),
            ],
            model=settings.llm_answer_model,
            temperature=0.0,
        )
    finally:
        await client.aclose()

    assert resp.content.strip(), "model returned empty content"
    assert resp.usage.total_tokens > 0
    assert resp.model  # model echoed back
