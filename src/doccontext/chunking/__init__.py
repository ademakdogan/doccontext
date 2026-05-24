from __future__ import annotations

from doccontext.chunking.base import Chunk, Chunker
from doccontext.chunking.recursive import RecursiveCharacterChunker
from doccontext.config import Settings, get_settings


def default_chunker(settings: Settings | None = None) -> Chunker:
    s = settings or get_settings()
    return RecursiveCharacterChunker(
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
    )


__all__ = ["Chunk", "Chunker", "RecursiveCharacterChunker", "default_chunker"]
