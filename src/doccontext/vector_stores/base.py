from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from doccontext.models.chunk import RetrievedChunk, StoredChunk


class VectorStore(ABC):
    """Abstract contract for a vector-store-backed chunk index.

    Implementations must be tenant-aware: every operation takes (client_id,
    corpus_ids) so one tenant's data never leaks into another's query.
    """

    @abstractmethod
    def ensure_collection(self, dim: int) -> None:
        """Create the collection with the given embedding dimensionality if absent."""

    @abstractmethod
    def upsert(self, chunks: Sequence[StoredChunk]) -> int:
        """Write/overwrite chunks. Returns the number written."""

    @abstractmethod
    def search(
        self,
        *,
        query_vector: list[float],
        client_id: str,
        corpus_ids: Sequence[str],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Return the top_k most-similar chunks, filtered to the given tenant + corpora."""

    @abstractmethod
    def delete_by_document(self, *, client_id: str, document_id: str) -> int:
        """Delete every chunk belonging to a document. Returns deleted count."""

    @abstractmethod
    def list_chunks_for_corpora(
        self,
        *,
        client_id: str,
        corpus_ids: Sequence[str],
        limit: int = 10000,
    ) -> list[RetrievedChunk]:
        """Return every chunk matching (client_id, corpus_ids) up to ``limit``.

        Used by the FULL_DOC branch of QueryDocuments to reconstruct full
        document text from its stored chunks. Score is reported as 0.0 since
        these are unscored scans.
        """
