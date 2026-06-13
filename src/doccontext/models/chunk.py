from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredChunk:
    """A chunk as it lives in (or is about to be written to) the vector store."""

    chunk_id: str
    document_id: str
    corpus_id: str
    client_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    file_type: str
    vector: list[float]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by a vector search, plus its similarity score."""

    chunk_id: str
    document_id: str
    corpus_id: str
    client_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    file_type: str
    score: float
