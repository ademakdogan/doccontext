from __future__ import annotations

from collections.abc import Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from doccontext.config import Settings, get_settings
from doccontext.models.chunk import RetrievedChunk, StoredChunk
from doccontext.vector_stores.base import VectorStore


class QdrantVectorStore(VectorStore):
    """Qdrant-backed store. One collection per tenant prefix; tenant + corpus
    filtering is done via payload keyword filters on every search.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._settings = s
        self._client = QdrantClient(
            host=s.qdrant_host,
            port=s.qdrant_port,
            api_key=s.qdrant_api_key or None,
            https=False,
        )
        self._collection = f"{s.qdrant_collection_prefix}_chunks"

    @property
    def collection_name(self) -> str:
        return self._collection

    @property
    def client(self) -> QdrantClient:
        return self._client

    # -- API --

    def ensure_collection(self, dim: int) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=dim, distance=qmodels.Distance.COSINE
            ),
        )
        # Payload indexes give us fast equality filters on the hot keys.
        for field in ("client_id", "corpus_id", "document_id"):
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )

    def upsert(self, chunks: Sequence[StoredChunk]) -> int:
        if not chunks:
            return 0
        points = [
            qmodels.PointStruct(
                id=c.chunk_id,
                vector=c.vector,
                payload={
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "corpus_id": c.corpus_id,
                    "client_id": c.client_id,
                    "chunk_index": c.chunk_index,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "text": c.text,
                    "file_type": c.file_type,
                },
            )
            for c in chunks
        ]
        self._client.upsert(collection_name=self._collection, points=points, wait=True)
        return len(points)

    def search(
        self,
        *,
        query_vector: list[float],
        client_id: str,
        corpus_ids: Sequence[str],
        top_k: int,
    ) -> list[RetrievedChunk]:
        must: list[qmodels.FieldCondition] = [
            qmodels.FieldCondition(
                key="client_id", match=qmodels.MatchValue(value=client_id)
            )
        ]
        if corpus_ids:
            must.append(
                qmodels.FieldCondition(
                    key="corpus_id",
                    match=qmodels.MatchAny(any=list(corpus_ids)),
                )
            )
        filt = qmodels.Filter(must=must)

        # query_points is the modern API; `search` is deprecated.
        resp = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            query_filter=filt,
            limit=top_k,
            with_payload=True,
        )
        out: list[RetrievedChunk] = []
        for point in resp.points:
            p = point.payload or {}
            out.append(
                RetrievedChunk(
                    chunk_id=str(p.get("chunk_id", point.id)),
                    document_id=str(p.get("document_id", "")),
                    corpus_id=str(p.get("corpus_id", "")),
                    client_id=str(p.get("client_id", "")),
                    chunk_index=int(p.get("chunk_index", 0)),
                    char_start=int(p.get("char_start", 0)),
                    char_end=int(p.get("char_end", 0)),
                    text=str(p.get("text", "")),
                    file_type=str(p.get("file_type", "")),
                    score=float(point.score),
                )
            )
        return out

    def list_chunks_for_corpora(
        self,
        *,
        client_id: str,
        corpus_ids: Sequence[str],
        limit: int = 10000,
    ) -> list[RetrievedChunk]:
        if not corpus_ids or limit <= 0:
            return []
        filt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="client_id", match=qmodels.MatchValue(value=client_id)
                ),
                qmodels.FieldCondition(
                    key="corpus_id", match=qmodels.MatchAny(any=list(corpus_ids))
                ),
            ]
        )
        out: list[RetrievedChunk] = []
        next_offset: object | None = None
        # Page size capped at 512 so a single overly-large limit doesn't demand
        # one gigantic response from Qdrant.
        page = min(limit, 512)
        while len(out) < limit:
            points, next_offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=filt,
                limit=min(page, limit - len(out)),
                with_payload=True,
                with_vectors=False,
                offset=next_offset,
            )
            for point in points:
                p = point.payload or {}
                out.append(
                    RetrievedChunk(
                        chunk_id=str(p.get("chunk_id", point.id)),
                        document_id=str(p.get("document_id", "")),
                        corpus_id=str(p.get("corpus_id", "")),
                        client_id=str(p.get("client_id", "")),
                        chunk_index=int(p.get("chunk_index", 0)),
                        char_start=int(p.get("char_start", 0)),
                        char_end=int(p.get("char_end", 0)),
                        text=str(p.get("text", "")),
                        file_type=str(p.get("file_type", "")),
                        score=0.0,
                    )
                )
            if next_offset is None:
                break
        return out

    def delete_by_document(self, *, client_id: str, document_id: str) -> int:
        filt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="client_id", match=qmodels.MatchValue(value=client_id)
                ),
                qmodels.FieldCondition(
                    key="document_id", match=qmodels.MatchValue(value=document_id)
                ),
            ]
        )
        # Count first so callers can log how many vectors were affected.
        count = self._client.count(
            collection_name=self._collection, count_filter=filt, exact=True
        ).count
        if count == 0:
            return 0
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(filter=filt),
            wait=True,
        )
        return count
