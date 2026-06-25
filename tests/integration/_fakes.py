"""Reusable test doubles for integration tests that construct a full servicer
but don't exercise every RPC path (e.g. the IndexDocument test doesn't need
a real LLM or embedder).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from doccontext.embeddings.base import Embedder
from doccontext.llm.base import LLMClient, LLMResponse, Message, Usage
from doccontext.models.chunk import RetrievedChunk, StoredChunk
from doccontext.vector_stores.base import VectorStore


class FakeEmbedder(Embedder):
    name = "fake"
    dim = 4

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # Deterministic, cheap, and dimension-consistent. The actual values
        # don't matter for tests that never read them.
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class FakeVectorStore(VectorStore):
    def __init__(self) -> None:
        self._chunks: list[StoredChunk] = []
        self.search_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    def ensure_collection(self, dim: int) -> None:
        return None

    def upsert(self, chunks: Sequence[StoredChunk]) -> int:
        self._chunks.extend(chunks)
        return len(chunks)

    def search(
        self,
        *,
        query_vector: list[float],
        client_id: str,
        corpus_ids: Sequence[str],
        top_k: int,
    ) -> list[RetrievedChunk]:
        self.search_calls.append(
            {
                "client_id": client_id,
                "corpus_ids": list(corpus_ids),
                "top_k": top_k,
            }
        )
        hits: list[RetrievedChunk] = []
        for c in self._chunks:
            if c.client_id != client_id:
                continue
            if corpus_ids and c.corpus_id not in corpus_ids:
                continue
            hits.append(
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    corpus_id=c.corpus_id,
                    client_id=c.client_id,
                    chunk_index=c.chunk_index,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    text=c.text,
                    file_type=c.file_type,
                    score=1.0 - 0.01 * c.chunk_index,
                )
            )
        return hits[:top_k]

    def delete_by_document(self, *, client_id: str, document_id: str) -> int:
        before = len(self._chunks)
        self._chunks = [
            c
            for c in self._chunks
            if not (c.client_id == client_id and c.document_id == document_id)
        ]
        return before - len(self._chunks)

    def list_chunks_for_corpora(
        self,
        *,
        client_id: str,
        corpus_ids: Sequence[str],
        limit: int = 10000,
    ) -> list[RetrievedChunk]:
        self.list_calls.append(
            {"client_id": client_id, "corpus_ids": list(corpus_ids), "limit": limit}
        )
        out: list[RetrievedChunk] = []
        for c in self._chunks:
            if c.client_id != client_id:
                continue
            if corpus_ids and c.corpus_id not in corpus_ids:
                continue
            out.append(
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    corpus_id=c.corpus_id,
                    client_id=c.client_id,
                    chunk_index=c.chunk_index,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    text=c.text,
                    file_type=c.file_type,
                    score=0.0,
                )
            )
            if len(out) >= limit:
                break
        return out


class FakeLLMClient(LLMClient):
    """Scripted LLM — returns successive replies from a queue.

    Each call pops one (content, usage) pair. Tests that want a deterministic
    router decision + answer simply enqueue two responses.
    """

    def __init__(self) -> None:
        self._replies: list[tuple[str, Usage]] = []
        self.calls: list[dict[str, Any]] = []

    def enqueue(
        self,
        content: str,
        *,
        prompt_tokens: int = 1,
        completion_tokens: int = 1,
    ) -> None:
        self._replies.append(
            (
                content,
                Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )
        )

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "messages": [(m.role, m.content) for m in messages],
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        if not self._replies:
            raise AssertionError(
                "FakeLLMClient.complete called but no scripted reply is queued"
            )
        content, usage = self._replies.pop(0)
        return LLMResponse(content=content, model=model, usage=usage)
