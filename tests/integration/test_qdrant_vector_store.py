from __future__ import annotations

import socket
import uuid
from collections.abc import Iterator

import pytest

from doccontext.config import Settings
from doccontext.models.chunk import StoredChunk
from doccontext.vector_stores.qdrant import QdrantVectorStore

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_qdrant(s: Settings) -> None:
    if not _port_open(s.qdrant_host, s.qdrant_port):
        pytest.skip(
            f"Qdrant not reachable at {s.qdrant_host}:{s.qdrant_port} — "
            "bring it up with `docker compose up -d qdrant`"
        )


@pytest.fixture
def store() -> Iterator[QdrantVectorStore]:
    """Each test gets its own collection so they cannot interfere."""
    prefix = f"dctest_{uuid.uuid4().hex[:8]}"
    settings = Settings(qdrant_collection_prefix=prefix)
    _require_qdrant(settings)
    vs = QdrantVectorStore(settings)
    vs.ensure_collection(dim=4)
    try:
        yield vs
    finally:
        try:
            vs.client.delete_collection(collection_name=vs.collection_name)
        except Exception:
            pass


def _chunk(
    *,
    chunk_id: str | None = None,
    document_id: str = "doc-1",
    corpus_id: str = "corpus-a",
    client_id: str = "tenant-1",
    chunk_index: int = 0,
    text: str = "hello world",
    vector: list[float] | None = None,
) -> StoredChunk:
    return StoredChunk(
        chunk_id=chunk_id or str(uuid.uuid4()),
        document_id=document_id,
        corpus_id=corpus_id,
        client_id=client_id,
        chunk_index=chunk_index,
        char_start=0,
        char_end=len(text),
        text=text,
        file_type="txt",
        vector=vector or [1.0, 0.0, 0.0, 0.0],
    )


# ---- ensure_collection -------------------------------------------------------


def test_ensure_collection_is_idempotent(store: QdrantVectorStore) -> None:
    # Fixture already created it once; a second call must not raise.
    store.ensure_collection(dim=4)
    collections = {c.name for c in store.client.get_collections().collections}
    assert store.collection_name in collections


# ---- upsert ------------------------------------------------------------------


def test_upsert_empty_returns_zero(store: QdrantVectorStore) -> None:
    assert store.upsert([]) == 0


def test_upsert_returns_written_count(store: QdrantVectorStore) -> None:
    chunks = [_chunk(vector=[1.0, 0.0, 0.0, 0.0]), _chunk(vector=[0.0, 1.0, 0.0, 0.0])]
    assert store.upsert(chunks) == 2


# ---- search ------------------------------------------------------------------


def test_search_ranks_by_cosine_similarity(store: QdrantVectorStore) -> None:
    near = _chunk(chunk_index=0, text="near", vector=[1.0, 0.0, 0.0, 0.0])
    far = _chunk(chunk_index=1, text="far", vector=[0.0, 1.0, 0.0, 0.0])
    store.upsert([near, far])

    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=5,
    )
    assert [h.text for h in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score


def test_search_filters_by_client_id(store: QdrantVectorStore) -> None:
    mine = _chunk(client_id="tenant-1", text="mine", vector=[1.0, 0.0, 0.0, 0.0])
    other = _chunk(client_id="tenant-2", text="other", vector=[1.0, 0.0, 0.0, 0.0])
    store.upsert([mine, other])

    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=[],
        top_k=10,
    )
    assert [h.text for h in hits] == ["mine"]
    assert all(h.client_id == "tenant-1" for h in hits)


def test_search_filters_by_corpus_ids(store: QdrantVectorStore) -> None:
    a = _chunk(corpus_id="corpus-a", text="a", vector=[1.0, 0.0, 0.0, 0.0])
    b = _chunk(corpus_id="corpus-b", text="b", vector=[1.0, 0.0, 0.0, 0.0])
    c = _chunk(corpus_id="corpus-c", text="c", vector=[1.0, 0.0, 0.0, 0.0])
    store.upsert([a, b, c])

    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a", "corpus-c"],
        top_k=10,
    )
    assert sorted(h.text for h in hits) == ["a", "c"]


def test_search_respects_top_k(store: QdrantVectorStore) -> None:
    store.upsert(
        [_chunk(chunk_index=i, vector=[1.0, 0.0, 0.0, 0.0]) for i in range(5)]
    )
    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=2,
    )
    assert len(hits) == 2


def test_search_returns_full_payload(store: QdrantVectorStore) -> None:
    c = _chunk(
        document_id="doc-42",
        chunk_index=7,
        text="payload check",
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    store.upsert([c])
    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=1,
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit.chunk_id == c.chunk_id
    assert hit.document_id == "doc-42"
    assert hit.corpus_id == "corpus-a"
    assert hit.client_id == "tenant-1"
    assert hit.chunk_index == 7
    assert hit.text == "payload check"
    assert hit.file_type == "txt"


# ---- delete_by_document ------------------------------------------------------


def test_delete_by_document_returns_deleted_count(store: QdrantVectorStore) -> None:
    store.upsert(
        [
            _chunk(document_id="doc-1", chunk_index=0, vector=[1.0, 0.0, 0.0, 0.0]),
            _chunk(document_id="doc-1", chunk_index=1, vector=[1.0, 0.0, 0.0, 0.0]),
            _chunk(document_id="doc-2", chunk_index=0, vector=[1.0, 0.0, 0.0, 0.0]),
        ]
    )
    assert store.delete_by_document(client_id="tenant-1", document_id="doc-1") == 2
    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=10,
    )
    assert [h.document_id for h in hits] == ["doc-2"]


def test_delete_by_document_missing_returns_zero(store: QdrantVectorStore) -> None:
    assert (
        store.delete_by_document(client_id="tenant-1", document_id="ghost")
        == 0
    )


def test_delete_by_document_is_tenant_scoped(store: QdrantVectorStore) -> None:
    store.upsert(
        [
            _chunk(client_id="tenant-1", document_id="doc-shared"),
            _chunk(client_id="tenant-2", document_id="doc-shared"),
        ]
    )
    assert (
        store.delete_by_document(client_id="tenant-1", document_id="doc-shared")
        == 1
    )
    # Tenant 2 still sees their chunk.
    hits = store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-2",
        corpus_ids=["corpus-a"],
        top_k=10,
    )
    assert len(hits) == 1
    assert hits[0].client_id == "tenant-2"
