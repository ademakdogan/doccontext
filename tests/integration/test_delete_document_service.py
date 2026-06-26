from __future__ import annotations

import asyncio
import json
import socket
import uuid
from collections.abc import AsyncIterator

import grpc
import pytest
from sqlalchemy import text

from doccontext.config import Settings
from doccontext.models.job import JobStatus, JobType
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.queue.rabbitmq import RabbitMQPublisher
from doccontext.repositories.job import (
    JobRepository,
    bootstrap_schema,
    create_engine,
)
from doccontext.services.delete_service import DeleteDocumentHandler
from doccontext.services.index_service import IndexDocumentHandler
<<<<<<< HEAD
from doccontext.services.query_service import QueryDocumentsHandler
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
from tests.integration._fakes import FakeEmbedder, FakeLLMClient, FakeVectorStore
=======
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
>>>>>>> 5831559 (test(services): DeleteDocument happy path + validation)

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def settings() -> Settings:
    s = Settings(
        rabbitmq_document_jobs_queue=f"doccontext_test_del_{uuid.uuid4().hex[:8]}",
    )
    missing: list[str] = []
    if not _port_open(s.rabbitmq_host, s.rabbitmq_port):
        missing.append("rabbitmq")
    if not _port_open(s.postgres_host, s.postgres_port):
        missing.append("postgres")
    if missing:
        pytest.skip(f"required services not reachable: {missing}")
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


@pytest.fixture
async def publisher(settings: Settings) -> AsyncIterator[RabbitMQPublisher]:
    p = RabbitMQPublisher(settings)
    try:
        yield p
    finally:
        await p.close()
        import aio_pika

        conn = await aio_pika.connect_robust(settings.rabbitmq_url)
        try:
            ch = await conn.channel()
            await ch.queue_delete(settings.rabbitmq_document_jobs_queue)
        finally:
            await conn.close()


@pytest.fixture
async def grpc_channel(
    settings: Settings, repo: JobRepository, publisher: RabbitMQPublisher
) -> AsyncIterator[grpc.aio.Channel]:
    servicer = DocContextServicer(
        index=IndexDocumentHandler(
            repository=repo, publisher=publisher, settings=settings
        ),
        status=GetIndexingJobStatusHandler(repository=repo),
        delete=DeleteDocumentHandler(
            repository=repo, publisher=publisher, settings=settings
        ),
<<<<<<< HEAD
        query=QueryDocumentsHandler(
            embedder=FakeEmbedder(),
            vector_store=FakeVectorStore(),
            llm=FakeLLMClient(),
            settings=settings,
        ),
=======
>>>>>>> 5831559 (test(services): DeleteDocument happy path + validation)
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


async def _drain_one_message(settings: Settings, timeout: float = 5.0) -> dict:
    import aio_pika

    conn = await aio_pika.connect_robust(settings.rabbitmq_url)
    try:
        ch = await conn.channel()
        q = await ch.declare_queue(
            settings.rabbitmq_document_jobs_queue, durable=True
        )
        got: asyncio.Future[dict] = asyncio.get_running_loop().create_future()

        async def on_message(message):
            async with message.process(requeue=False):
                got.set_result(json.loads(message.body.decode("utf-8")))

        consumer_tag = await q.consume(on_message)
        try:
            return await asyncio.wait_for(got, timeout=timeout)
        finally:
            await q.cancel(consumer_tag)
    finally:
        await conn.close()


async def test_delete_document_creates_queued_job_and_publishes_envelope(
    settings: Settings,
    repo: JobRepository,
    grpc_channel: grpc.aio.Channel,
) -> None:
    stub = pb_grpc.DocContextStub(grpc_channel)
    resp = await stub.DeleteDocument(
        pb.DeleteDocumentRequest(
            document_id="doc-del-1",
            client_id="tenant-1",
            user_id="u-1",
        )
    )
    assert resp.job_id
    assert resp.status == pb.QUEUED

    job = await repo.get(resp.job_id)
    assert job is not None
    assert job.status is JobStatus.QUEUED
    assert job.job_type is JobType.DELETE_DOCUMENT
    assert job.document_id == "doc-del-1"
    assert job.client_id == "tenant-1"
    assert job.file_path is None

    envelope = await _drain_one_message(settings)
    assert envelope["job_id"] == resp.job_id
    assert envelope["job_type"] == "DELETE_DOCUMENT"
    assert envelope["document_id"] == "doc-del-1"
    assert envelope["client_id"] == "tenant-1"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(document_id="d"), "client_id is required"),
        (dict(client_id="c"), "document_id is required"),
    ],
)
async def test_delete_document_rejects_invalid_requests(
    grpc_channel: grpc.aio.Channel, kwargs, expected
) -> None:
    stub = pb_grpc.DocContextStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as ei:
        await stub.DeleteDocument(pb.DeleteDocumentRequest(**kwargs))
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert expected in ei.value.details()
