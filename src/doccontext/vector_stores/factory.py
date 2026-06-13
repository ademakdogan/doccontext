from __future__ import annotations

from doccontext.config import Settings, get_settings
from doccontext.vector_stores.base import VectorStore


class UnknownVectorStoreProvider(ValueError):
    pass


_KNOWN_PROVIDERS = {"qdrant", "weaviate", "milvus", "pgvector", "pinecone"}


def get_vector_store(settings: Settings | None = None) -> VectorStore:
    s = settings or get_settings()
    provider = s.vector_store_provider
    if provider == "qdrant":
        from doccontext.vector_stores.qdrant import QdrantVectorStore

        return QdrantVectorStore(s)
    if provider in _KNOWN_PROVIDERS:
        raise NotImplementedError(
            f"vector store provider {provider!r} is reserved but not yet implemented"
        )
    raise UnknownVectorStoreProvider(f"unknown vector store provider: {provider!r}")
