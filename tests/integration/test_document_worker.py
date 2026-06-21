from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import text

from doccontext.chunking import default_chunker
from doccontext.config import Settings
from doccontext.embeddings.base import Embedder
from doccontext.ids import chunk_id_for, new_job_id
from doccontext.models.job import JobStatus, JobType
from doccontext.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from doccontext.repositories.job import (
    JobRepository,
    bootstrap_schema,
    create_engine,
)
from doccontext.vector_stores.qdrant import QdrantVectorStore
from doccontext.workers.document_worker import DocumentWorker, run_worker
from doccontext.workers.envelope import JobEnvelope

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _FakeEmbedder(Embedder):
    """Deterministic 4-d embedder so worker tests don't spin up MiniLM."""

    name = "fake"
    dim = 4

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def settings() -> Settings:
    s = Settings(qdrant_collection_prefix=f"dctest_{uuid.uuid4().hex[:8]}")
    missing = []
    if not _port_open(s.qdrant_host, s.qdrant_port):
        missing.append("qdrant")
    if not _port_open(s.postgres_host, s.postgres_port):
        missing.append("postgres")
    if not _port_open(s.rabbitmq_host, s.rabbitmq_port):
        missing.append("rabbitmq")
    if missing:
        pytest.skip(
            f"required services not reachable: {missing} — "
            "bring them up with `docker compose up -d`"
        )
    return s


@pytest.fixture
async def vector_store(settings: Settings) -> AsyncIterator[QdrantVectorStore]:
    vs = QdrantVectorStore(settings)
    vs.ensure_collection(dim=_FakeEmbedder.dim)
    try:
        yield vs
    finally:
        try:
            vs.client.delete_collection(collection_name=vs.collection_name)
        except Exception:
            pass


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
def worker(
    settings: Settings, vector_store: QdrantVectorStore, repo: JobRepository
) -> DocumentWorker:
    return DocumentWorker(
        repository=repo,
        vector_store=vector_store,
        embedder=_FakeEmbedder(),
        chunker=default_chunker(settings),
    )


async def _seed_document(
    repo: JobRepository,
    *,
    file_path: Path,
    client_id: str = "tenant-1",
    corpus_id: str = "corpus-a",
    document_id: str = "doc-1",
    job_type: JobType = JobType.INDEX_DOCUMENT,
) -> JobEnvelope:
    job_id = new_job_id()
    await repo.create(
        job_id=job_id,
        job_type=job_type,
        client_id=client_id,
        corpus_id=corpus_id,
        document_id=document_id,
        file_type="txt",
        file_path=str(file_path) if job_type is JobType.INDEX_DOCUMENT else None,
    )
    return JobEnvelope(
        job_id=job_id,
        job_type=job_type,
        client_id=client_id,
        corpus_id=corpus_id,
        document_id=document_id,
        file_type="txt",
        file_path=str(file_path) if job_type is JobType.INDEX_DOCUMENT else None,
    )


async def test_worker_indexes_a_txt_document(
    tmp_path: Path,
    worker: DocumentWorker,
    vector_store: QdrantVectorStore,
    repo: JobRepository,
) -> None:
    file = tmp_path / "doc.txt"
    file.write_text("first paragraph\n\nsecond paragraph\n\nthird paragraph")
    env = await _seed_document(repo, file_path=file)

    await worker.handle(env.to_payload())

    hits = vector_store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id=env.client_id,
        corpus_ids=[env.corpus_id],
        top_k=10,
    )
    assert len(hits) >= 1
    assert all(h.document_id == env.document_id for h in hits)
    # Deterministic chunk IDs.
    assert hits[0].chunk_id == chunk_id_for(env.document_id, hits[0].chunk_index)

    job = await repo.get(env.job_id)
    assert job is not None and job.status is JobStatus.SUCCEEDED


async def test_worker_deletes_every_chunk_for_a_document(
    tmp_path: Path,
    worker: DocumentWorker,
    vector_store: QdrantVectorStore,
    repo: JobRepository,
) -> None:
    file = tmp_path / "doc.txt"
    file.write_text("alpha\n\nbeta\n\ngamma")
    index_env = await _seed_document(repo, file_path=file, document_id="doc-del")
    await worker.handle(index_env.to_payload())

    pre = vector_store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=10,
    )
    assert len(pre) >= 1

    delete_env = await _seed_document(
        repo,
        file_path=file,
        document_id="doc-del",
        job_type=JobType.DELETE_DOCUMENT,
    )
    await worker.handle(delete_env.to_payload())

    post = vector_store.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        client_id="tenant-1",
        corpus_ids=["corpus-a"],
        top_k=10,
    )
    assert [h.document_id for h in post] == []
    job = await repo.get(delete_env.job_id)
    assert job is not None and job.status is JobStatus.SUCCEEDED


async def test_worker_marks_failed_when_file_missing(
    tmp_path: Path,
    worker: DocumentWorker,
    repo: JobRepository,
) -> None:
    missing = tmp_path / "does_not_exist.txt"
    env = await _seed_document(repo, file_path=missing)
    with pytest.raises(Exception):
        await worker.handle(env.to_payload())
    job = await repo.get(env.job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error_message


async def test_run_worker_processes_envelope_from_queue(
    tmp_path: Path,
    settings: Settings,
    worker: DocumentWorker,
    repo: JobRepository,
    vector_store: QdrantVectorStore,
) -> None:
    """End-to-end: publish an envelope to RabbitMQ, the worker loop consumes and processes it."""
    queue_name = f"doccontext_worker_test_{uuid.uuid4().hex[:8]}"
    # Override the configured queue so this test doesn't collide with others.
    settings_override = settings.model_copy(update={"rabbitmq_document_jobs_queue": queue_name})

    file = tmp_path / "doc.txt"
    file.write_text("queue-driven content\n\nmore content")
    env = await _seed_document(repo, file_path=file, document_id="doc-q")

    publisher = RabbitMQPublisher(settings_override)
    consumer = RabbitMQConsumer(settings_override)

    try:
        await publisher.publish(queue=queue_name, payload=env.to_payload())

        task = asyncio.create_task(
            run_worker(consumer=consumer, worker=worker, settings=settings_override)
        )
        try:
            # Poll the repo until the worker has transitioned the job.
            deadline = asyncio.get_running_loop().time() + 10.0
            while True:
                job = await repo.get(env.job_id)
                if job is not None and job.status is JobStatus.SUCCEEDED:
                    break
                if asyncio.get_running_loop().time() > deadline:
                    pytest.fail(
                        f"worker did not complete job {env.job_id} in time; "
                        f"current status={job.status if job else 'missing'}"
                    )
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        hits = vector_store.search(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            client_id="tenant-1",
            corpus_ids=["corpus-a"],
            top_k=10,
        )
        assert any(h.document_id == "doc-q" for h in hits)
    finally:
        await publisher.close()
        await consumer.close()
        # Drop the test queue.
        import aio_pika

        conn = await aio_pika.connect_robust(settings_override.rabbitmq_url)
        try:
            ch = await conn.channel()
            await ch.queue_delete(queue_name)
        finally:
            await conn.close()
