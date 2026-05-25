from __future__ import annotations

from functools import lru_cache

from doccontext.config import Settings, get_settings
from doccontext.embeddings.base import Embedder


class UnknownEmbeddingProvider(ValueError):
    pass


# Keys must match EMBEDDING_PROVIDER values in .env. New providers register
# themselves here; no caller code changes when adding e5/bge/arctic/mxbai.
_KNOWN_PROVIDERS = {"minilm", "e5", "bge-m3", "arctic-l-v2", "mxbai"}


@lru_cache(maxsize=None)
def _build(provider: str) -> Embedder:
    if provider == "minilm":
        from doccontext.embeddings.minilm import MiniLMEmbedder

        return MiniLMEmbedder()
    if provider in _KNOWN_PROVIDERS:
        raise NotImplementedError(
            f"embedding provider {provider!r} is reserved but not yet implemented"
        )
    raise UnknownEmbeddingProvider(f"unknown embedding provider: {provider!r}")


def get_embedder(settings: Settings | None = None) -> Embedder:
    s = settings or get_settings()
    return _build(s.embedding_provider)


def clear_embedder_cache() -> None:
    _build.cache_clear()
