from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncIterator

import grpc
import pytest
from sqlalchemy import text

from doccontext.config import Settings
from doccontext.ids import new_job_id
from doccontext.models.job import JobType
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.repositories.job import (
    JobRepository,
    bootstrap_schema,
    create_engine,
)
<<<<<<< HEAD
from doccontext.services.delete_service import DeleteDocumentHandler
from doccontext.services.index_service import IndexDocumentHandler
from doccontext.services.query_service import QueryDocumentsHandler
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
from tests.integration._fakes import FakeEmbedder, FakeLLMClient, FakeVectorStore
=======
from doccontext.services.index_service import IndexDocumentHandler
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
>>>>>>> e4497c5 (test(services): GetIndexingJobStatus happy paths + not-found + validation)

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    if not _port_open(s.postgres_host, s.postgres_port):
        pytest.skip("postgres not reachable")
    return s


@pytest.fixture
async def repo(settings: Settings) -> AsyncIterator[JobRepository]:
    engine = create_engine(settings)
    await bootstrap_schema(engine)
    try:
        yield JobRepository(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE indexing_jobs"))
        await engine.dispose()


class _NullPublisher:
    async def publish(self, **_):
        raise AssertionError("publisher should not be used from status tests")

    async def close(self):
        pass


@pytest.fixture
async def grpc_channel(
    settings: Settings, repo: JobRepository
) -> AsyncIterator[grpc.aio.Channel]:
<<<<<<< HEAD
    null_pub = _NullPublisher()
    servicer = DocContextServicer(
        index=IndexDocumentHandler(
            repository=repo, publisher=null_pub, settings=settings  # type: ignore[arg-type]
        ),
        status=GetIndexingJobStatusHandler(repository=repo),
        delete=DeleteDocumentHandler(
            repository=repo, publisher=null_pub, settings=settings  # type: ignore[arg-type]
        ),
        query=QueryDocumentsHandler(
            embedder=FakeEmbedder(),
            vector_store=FakeVectorStore(),
            llm=FakeLLMClient(),
            settings=settings,
        ),
=======
    servicer = DocContextServicer(
        index=IndexDocumentHandler(
            repository=repo, publisher=_NullPublisher(), settings=settings  # type: ignore[arg-type]
        ),
        status=GetIndexingJobStatusHandler(repository=repo),
>>>>>>> e4497c5 (test(services): GetIndexingJobStatus happy paths + not-found + validation)
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


async def test_get_status_returns_queued_for_fresh_job(
    repo: JobRepository, grpc_channel: grpc.aio.Channel
) -> None:
    job_id = new_job_id()
    await repo.create(
        job_id=job_id,
        job_type=JobType.INDEX_DOCUMENT,
        client_id="tenant-1",
        corpus_id="corpus-a",
        document_id="doc-status-1",
        file_type="pdf",
        file_path="/tmp/x.pdf",
    )
    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.GetIndexingJobStatus(
        pb.GetIndexingJobStatusRequest(job_id=job_id)
    )
    assert resp.job_id == job_id
    assert resp.document_id == "doc-status-1"
    assert resp.status == pb.QUEUED
    assert resp.error_message == ""


async def test_get_status_returns_failed_with_error_message(
    repo: JobRepository, grpc_channel: grpc.aio.Channel
) -> None:
    job_id = new_job_id()
    await repo.create(
        job_id=job_id,
        job_type=JobType.INDEX_DOCUMENT,
        client_id="tenant-1",
        corpus_id="corpus-a",
        document_id="doc-status-2",
        file_type="pdf",
        file_path="/tmp/x.pdf",
    )
    await repo.mark_failed(job_id, error_message="boom")

    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.GetIndexingJobStatus(
        pb.GetIndexingJobStatusRequest(job_id=job_id)
    )
    assert resp.status == pb.FAILED
    assert resp.error_message == "boom"


async def test_get_status_returns_not_found_for_missing_job(
    grpc_channel: grpc.aio.Channel,
) -> None:
    stub = pb_grpc.DocContextStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as ei:
        await stub.GetIndexingJobStatus(
            pb.GetIndexingJobStatusRequest(job_id=str(uuid.uuid4()))
        )
    assert ei.value.code() == grpc.StatusCode.NOT_FOUND


async def test_get_status_rejects_missing_job_id(
    grpc_channel: grpc.aio.Channel,
) -> None:
    stub = pb_grpc.DocContextStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as ei:
        await stub.GetIndexingJobStatus(pb.GetIndexingJobStatusRequest())
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT
