"""QueryDocuments integration tests.

These use a real gRPC in-process server but stub the LLM (FakeLLMClient)
and vector store (FakeVectorStore) so the tests are deterministic and
don't depend on OpenRouter or Qdrant availability. We still exercise the
full wire: proto request → servicer → handler → fake backends.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import grpc
import pytest

from doccontext.config import Settings
from doccontext.logging_config import LogChannel, channel_logger_name, configure_logging
from doccontext.models.chunk import StoredChunk
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.services.delete_service import DeleteDocumentHandler
from doccontext.services.index_service import IndexDocumentHandler
from doccontext.services.query_service import QueryDocumentsHandler
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
from tests.integration._fakes import FakeEmbedder, FakeLLMClient, FakeVectorStore

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings — each test gets its own log dir + low concurrency cap
    so concurrency tests finish fast."""
    return Settings(
        log_dir=tmp_path / "logs",
        log_file_index_document=tmp_path / "logs" / "index_document.log",
        log_file_get_indexing_job_status=tmp_path
        / "logs"
        / "get_indexing_job_status.log",
        log_file_query_documents=tmp_path / "logs" / "query_documents.log",
        log_file_delete_document=tmp_path / "logs" / "delete_document.log",
        log_file_worker=tmp_path / "logs" / "worker.log",
        max_concurrent_queries=2,
    )


@pytest.fixture
def vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


class _NullRepo:
    """Status/Index/Delete aren't exercised here; servicer only needs the attrs."""

    async def create(self, **_):
        return None

    async def get(self, _):
        return None

    async def mark_running(self, _):
        pass

    async def mark_succeeded(self, _):
        pass

    async def mark_failed(self, _, error_message):
        pass


class _NullPublisher:
    async def publish(self, **_):
        pass

    async def close(self):
        pass


@pytest.fixture
async def grpc_channel(
    settings: Settings,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
    embedder: FakeEmbedder,
) -> AsyncIterator[grpc.aio.Channel]:
    configure_logging(settings)
    query_handler = QueryDocumentsHandler(
        embedder=embedder,
        vector_store=vector_store,
        llm=llm,
        settings=settings,
    )
    repo = _NullRepo()
    pub = _NullPublisher()
    servicer = DocContextServicer(
        index=IndexDocumentHandler(
            repository=repo, publisher=pub, settings=settings  # type: ignore[arg-type]
        ),
        status=GetIndexingJobStatusHandler(repository=repo),  # type: ignore[arg-type]
        delete=DeleteDocumentHandler(
            repository=repo, publisher=pub, settings=settings  # type: ignore[arg-type]
        ),
        query=query_handler,
    )
    server = grpc.aio.server()
    pb_grpc.add_DocContextServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield channel
    finally:
        await channel.close()
        await server.stop(grace=None)


def _seed(store: FakeVectorStore, *chunks: StoredChunk) -> None:
    store.upsert(chunks)


def _mk_chunk(
    *,
    chunk_id: str,
    document_id: str,
    corpus_id: str,
    client_id: str,
    chunk_index: int,
    char_start: int,
    char_end: int,
    text: str,
) -> StoredChunk:
    return StoredChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        corpus_id=corpus_id,
        client_id=client_id,
        chunk_index=chunk_index,
        char_start=char_start,
        char_end=char_end,
        text=text,
        file_type="txt",
        vector=[0.1, 0.2, 0.3, 0.4],
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_section_path_embeds_searches_and_returns_answer_with_citations(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c1",
            document_id="doc-1",
            corpus_id="sess-a",
            client_id="tenant-1",
            chunk_index=0,
            char_start=0,
            char_end=40,
            text="The capital of France is Paris.",
        ),
        _mk_chunk(
            chunk_id="c2",
            document_id="doc-1",
            corpus_id="sess-a",
            client_id="tenant-1",
            chunk_index=1,
            char_start=30,
            char_end=80,
            text="France uses the euro as its currency.",
        ),
    )
    llm.enqueue(
        json.dumps({"route": "SECTION", "confidence": 0.82}),
        prompt_tokens=12,
        completion_tokens=4,
    )
    llm.enqueue(
        json.dumps(
            {
                "answer": "Paris.",
                "citations": [
                    {"chunk_id": "c1", "document_id": "doc-1", "quote": "Paris"}
                ],
            }
        ),
        prompt_tokens=30,
        completion_tokens=3,
    )

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="tenant-1",
            user_id="u-1",
            chat_session_id="chat-1",
            corpus_ids=["sess-a"],
            prompt="What is the capital of France?",
            top_k=2,
        )
    )

    assert resp.answer == "Paris."
    assert resp.used_route == pb.SECTION
    assert abs(resp.confidence - 0.82) < 1e-6
    assert len(resp.citations) == 2  # top_k hits, corpus-scoped
    assert {c.document_id for c in resp.citations} == {"doc-1"}
    # Router first, answer second, both directed at their configured models.
    assert len(llm.calls) == 2
    assert llm.calls[0]["model"] == "openai/gpt-5-mini"
    assert llm.calls[1]["model"] == "openai/gpt-5-mini"
    # User prompt goes first so provider prompt caching can hit.
    assert llm.calls[0]["messages"][0] == ("user", "What is the capital of France?")
    # Search was tenant+corpus scoped.
    assert vector_store.search_calls == [
        {"client_id": "tenant-1", "corpus_ids": ["sess-a"], "top_k": 2}
    ]
    # FULL_DOC listing was NOT invoked on the SECTION path.
    assert vector_store.list_calls == []


async def test_full_doc_path_lists_chunks_and_concatenates_documents(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    # Two chunks on the same document with a deliberate 10-char overlap that
    # the handler must dedupe when reconstructing the document text.
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="d1-0",
            document_id="doc-big",
            corpus_id="sess-x",
            client_id="tenant-7",
            chunk_index=0,
            char_start=0,
            char_end=20,
            text="Intro paragraph.AAAA",
        ),
        _mk_chunk(
            chunk_id="d1-1",
            document_id="doc-big",
            corpus_id="sess-x",
            client_id="tenant-7",
            chunk_index=1,
            char_start=16,
            char_end=36,
            text="AAAAsecond section.X",
        ),
    )
    llm.enqueue(json.dumps({"route": "FULL_DOC", "confidence": 0.9}))
    llm.enqueue(
        json.dumps(
            {
                "answer": "Summary: intro then a second section.",
                "citations": [
                    {"chunk_id": "", "document_id": "doc-big", "quote": "intro"}
                ],
            }
        )
    )

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="tenant-7",
            corpus_ids=["sess-x"],
            prompt="Summarise the document",
        )
    )

    assert resp.used_route == pb.FULL_DOC
    assert resp.answer.startswith("Summary:")
    assert len(resp.citations) == 1
    cit = resp.citations[0]
    assert cit.document_id == "doc-big"
    assert cit.char_start == 0
    assert cit.char_end == 36
    # Handler asked for the full chunk set once.
    assert vector_store.list_calls == [
        {"client_id": "tenant-7", "corpus_ids": ["sess-x"], "limit": 10000}
    ]
    # Answer-stage message must contain the reconstructed text with the 5-char
    # overlap trimmed (so "AAAA" appears only once).
    answer_messages = llm.calls[1]["messages"]
    joined = "\n".join(content for _, content in answer_messages)
    assert "Intro paragraph.AAAAsecond section.X" in joined
    # Embedder is NOT invoked on the FULL_DOC path.
    assert vector_store.search_calls == []


async def test_multi_corpus_query_scopes_search_to_all_ids(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="a",
            document_id="d-a",
            corpus_id="sess-a",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=10,
            text="alpha",
        ),
        _mk_chunk(
            chunk_id="b",
            document_id="d-b",
            corpus_id="sess-b",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=10,
            text="beta",
        ),
        _mk_chunk(
            chunk_id="c",
            document_id="d-c",
            corpus_id="sess-other",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=10,
            text="other",
        ),
    )
    llm.enqueue(json.dumps({"route": "SECTION", "confidence": 0.5}))
    llm.enqueue(json.dumps({"answer": "ok", "citations": []}))

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="t",
            corpus_ids=["sess-a", "sess-b"],
            prompt="anything",
            top_k=5,
        )
    )

    # Both in-scope corpora appear; the out-of-scope one does not.
    citation_docs = {c.document_id for c in resp.citations}
    assert citation_docs == {"d-a", "d-b"}
    assert vector_store.search_calls[0]["corpus_ids"] == ["sess-a", "sess-b"]


async def test_tenant_isolation_filters_out_other_clients_chunks(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="mine",
            document_id="d-mine",
            corpus_id="shared",
            client_id="tenant-A",
            chunk_index=0,
            char_start=0,
            char_end=10,
            text="mine",
        ),
        _mk_chunk(
            chunk_id="theirs",
            document_id="d-theirs",
            corpus_id="shared",
            client_id="tenant-B",
            chunk_index=0,
            char_start=0,
            char_end=10,
            text="theirs",
        ),
    )
    llm.enqueue(json.dumps({"route": "SECTION", "confidence": 0.5}))
    llm.enqueue(json.dumps({"answer": "ok", "citations": []}))

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="tenant-A",
            corpus_ids=["shared"],
            prompt="anything",
        )
    )
    assert {c.document_id for c in resp.citations} == {"d-mine"}


# ---------------------------------------------------------------------------
# History window
# ---------------------------------------------------------------------------


async def test_history_window_zero_omits_history_entirely(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c",
            document_id="d",
            corpus_id="s",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=5,
            text="hello",
        ),
    )
    llm.enqueue(json.dumps({"route": "SECTION", "confidence": 0.3}))
    llm.enqueue(json.dumps({"answer": "ok", "citations": []}))

    stub = pb_grpc.DocContextStub(grpc_channel)
    await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="t",
            corpus_ids=["s"],
            prompt="anything",
            history_window=0,
            history=[
                pb.HistoryMessage(role="user", content="earlier Q"),
                pb.HistoryMessage(role="assistant", content="earlier A"),
            ],
        )
    )
    answer_messages = llm.calls[1]["messages"]
    # Neither the earlier user turn nor the assistant turn should appear.
    assert not any(content == "earlier Q" for _, content in answer_messages)
    assert not any(content == "earlier A" for _, content in answer_messages)


async def test_history_window_keeps_only_last_n_pairs(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c",
            document_id="d",
            corpus_id="s",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=5,
            text="hello",
        ),
    )
    llm.enqueue(json.dumps({"route": "SECTION", "confidence": 0.3}))
    llm.enqueue(json.dumps({"answer": "ok", "citations": []}))

    stub = pb_grpc.DocContextStub(grpc_channel)
    await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="t",
            corpus_ids=["s"],
            prompt="current",
            history_window=1,
            history=[
                pb.HistoryMessage(role="user", content="q-oldest"),
                pb.HistoryMessage(role="assistant", content="a-oldest"),
                pb.HistoryMessage(role="user", content="q-newest"),
                pb.HistoryMessage(role="assistant", content="a-newest"),
            ],
        )
    )
    answer_messages = llm.calls[1]["messages"]
    contents = [c for _, c in answer_messages]
    assert "q-newest" in contents
    assert "a-newest" in contents
    assert "q-oldest" not in contents
    assert "a-oldest" not in contents


# ---------------------------------------------------------------------------
# Concurrency cap
# ---------------------------------------------------------------------------


async def test_semaphore_caps_concurrent_llm_calls(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
    settings: Settings,
) -> None:
    """Swap in a counting-LLM that exposes max-in-flight, then fire more
    requests than the cap and verify the observed peak never exceeds it."""
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c",
            document_id="d",
            corpus_id="s",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=5,
            text="hello",
        ),
    )

    class CountingLLM:
        def __init__(self) -> None:
            self.in_flight = 0
            self.peak = 0
            self._lock = asyncio.Lock()

        async def complete(self, messages, *, model, temperature=0.0, response_format=None):
            async with self._lock:
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
            try:
                # Simulate latency so overlapping requests actually stack.
                await asyncio.sleep(0.05)
                from doccontext.llm.base import LLMResponse, Usage

                # Alternate router/answer based on response_format (both JSON).
                if any(m.role == "system" and "routing classifier" in m.content for m in messages):
                    content = json.dumps({"route": "SECTION", "confidence": 0.1})
                else:
                    content = json.dumps({"answer": "ok", "citations": []})
                return LLMResponse(
                    content=content,
                    model=model,
                    usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
            finally:
                async with self._lock:
                    self.in_flight -= 1

        async def aclose(self) -> None:
            pass

    counting = CountingLLM()
    # Rewire the handler's LLM in-place. The handler's semaphore came from the
    # Settings used when constructing the grpc_channel fixture — cap is 2.
    from doccontext.services import query_service as qs_mod  # noqa: F401

    # Reach into the servicer via the fixture's server. Simpler: rebuild
    # handler + servicer is heavy; instead, monkey-patch the shared llm fake
    # used by the real handler. The `llm` fixture is what was injected.
    llm._replies = []  # sanity: scripted replies should not be touched

    # Build a fresh handler + server using the counting LLM, cap=2.
    handler = QueryDocumentsHandler(
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        llm=counting,  # type: ignore[arg-type]
        settings=settings,
    )
    assert settings.max_concurrent_queries == 2

    class _R:
        async def create(self, **_):
            pass

        async def get(self, _):
            return None

        async def mark_succeeded(self, _):
            pass

        async def mark_failed(self, _, error_message):
            pass

        async def mark_running(self, _):
            pass

    class _P:
        async def publish(self, **_):
            pass

        async def close(self):
            pass

    servicer = DocContextServicer(
        index=IndexDocumentHandler(repository=_R(), publisher=_P(), settings=settings),  # type: ignore[arg-type]
        status=GetIndexingJobStatusHandler(repository=_R()),  # type: ignore[arg-type]
        delete=DeleteDocumentHandler(repository=_R(), publisher=_P(), settings=settings),  # type: ignore[arg-type]
        query=handler,
    )
    server = grpc.aio.server()
    pb_grpc.add_DocContextServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = pb_grpc.DocContextStub(channel)
        reqs = [
            stub.QueryDocuments(
                pb.QueryDocumentsRequest(
                    client_id="t",
                    corpus_ids=["s"],
                    prompt=f"q-{i}",
                )
            )
            for i in range(6)
        ]
        await asyncio.gather(*reqs)
    finally:
        await channel.close()
        await server.stop(grace=None)

    # The semaphore holds across both stages for one request, so two concurrent
    # requests = 2 concurrent LLM calls at most.
    assert counting.peak <= 2
    assert counting.peak >= 2  # we fired 6 requests; at least 2 overlapped


# ---------------------------------------------------------------------------
# Validation + structured logs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(corpus_ids=["s"], prompt="p"), "client_id is required"),
        (dict(client_id="t", corpus_ids=["s"]), "prompt is required"),
        (dict(client_id="t", prompt="p"), "corpus_ids must not be empty"),
    ],
)
async def test_query_documents_rejects_invalid_requests(
    grpc_channel: grpc.aio.Channel, kwargs, expected
) -> None:
    stub = pb_grpc.DocContextStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as ei:
        await stub.QueryDocuments(pb.QueryDocumentsRequest(**kwargs))
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert expected in ei.value.details()


async def test_structured_log_carries_route_tokens_and_duration(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
    settings: Settings,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c",
            document_id="d",
            corpus_id="s",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=5,
            text="hello",
        ),
    )
    llm.enqueue(
        json.dumps({"route": "SECTION", "confidence": 0.77}),
        prompt_tokens=9,
        completion_tokens=3,
    )
    llm.enqueue(
        json.dumps({"answer": "ok", "citations": []}),
        prompt_tokens=21,
        completion_tokens=6,
    )

    stub = pb_grpc.DocContextStub(grpc_channel)
    await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="t",
            user_id="u",
            chat_session_id="sess",
            corpus_ids=["s"],
            prompt="hi",
            top_k=3,
        )
    )

    # Flush the channel logger's file handler so the assertion below sees the line.
    logger_name = channel_logger_name(LogChannel.QUERY_DOCUMENTS)
    for handler in logging.getLogger(logger_name).handlers:
        handler.flush()

    log_text = settings.log_file_query_documents.read_text(encoding="utf-8").strip()
    assert log_text, "expected at least one query_documents log line"
    # Each line is an independent JSON document.
    event = json.loads(log_text.splitlines()[-1])
    assert event["route"] == "SECTION"
    assert abs(event["confidence"] - 0.77) < 1e-6
    assert event["input_tokens"] == 9 + 21
    assert event["output_tokens"] == 3 + 6
    assert event["total_tokens"] == (9 + 3) + (21 + 6)
    assert event["top_k"] == 3
    assert event["corpus_ids"] == ["s"]
    assert event["client_id"] == "t"
    assert event["chat_session_id"] == "sess"
    assert event["model_router"] == settings.llm_router_model
    assert event["model_answer"] == settings.llm_answer_model
    assert event["duration_ms"] >= 0
    assert event["event"] == "query_documents answered"


async def test_malformed_router_json_falls_back_to_section(
    grpc_channel: grpc.aio.Channel,
    vector_store: FakeVectorStore,
    llm: FakeLLMClient,
) -> None:
    _seed(
        vector_store,
        _mk_chunk(
            chunk_id="c",
            document_id="d",
            corpus_id="s",
            client_id="t",
            chunk_index=0,
            char_start=0,
            char_end=5,
            text="hello",
        ),
    )
    llm.enqueue("not-json at all")  # router reply is garbage
    llm.enqueue(json.dumps({"answer": "fallback", "citations": []}))

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.QueryDocuments(
        pb.QueryDocumentsRequest(
            client_id="t",
            corpus_ids=["s"],
            prompt="q",
        )
    )
    assert resp.used_route == pb.SECTION  # safe default
    assert resp.confidence == 0.0
    assert resp.answer == "fallback"
