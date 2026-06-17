from __future__ import annotations

from doccontext.config import Settings, get_settings
from doccontext.llm.base import LLMClient


class UnknownLLMProvider(ValueError):
    pass


_KNOWN_PROVIDERS = {"openrouter", "openai", "anthropic", "ollama"}


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Build an LLM client from settings.

    Only 'openrouter' is wired up today; other provider keys are reserved
    so migrations are a one-file add + one branch here.
    """
    s = settings or get_settings()
    provider = getattr(s, "llm_provider", "openrouter")
    if provider == "openrouter":
        from doccontext.llm.openrouter import OpenRouterClient

        return OpenRouterClient(s)
    if provider in _KNOWN_PROVIDERS:
        raise NotImplementedError(
            f"LLM provider {provider!r} is reserved but not yet implemented"
        )
    raise UnknownLLMProvider(f"unknown LLM provider: {provider!r}")
