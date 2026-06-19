from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from doccontext.config import Settings
from doccontext.models.job import JobStatus, JobType
from doccontext.repositories.job import (
    JobRepository,
    bootstrap_schema,
    create_engine,
)

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_postgres(s: Settings) -> None:
    if not _port_open(s.postgres_host, s.postgres_port):
        pytest.skip(
            f"Postgres not reachable at {s.postgres_host}:{s.postgres_port} — "
            "bring it up with `docker compose up -d postgres`"
        )


@pytest.fixture(scope="module")
def settings() -> Settings:
    s = Settings()
    _require_postgres(s)
    return s


@pytest.fixture
async def repo(settings: Settings) -> AsyncIterator[JobRepository]:
    """Per-test: bootstrap schema, truncate rows on teardown."""
    engine = create_engine(settings)
    await bootstrap_schema(engine)
    try:
        yield JobRepository(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE indexing_jobs"))
        await engine.dispose()


def _job_args(**overrides):
    base = dict(
        job_id=str(uuid.uuid4()),
        job_type=JobType.INDEX_DOCUMENT,
        client_id="tenant-1",
        corpus_id="corpus-a",
        document_id="doc-1",
        file_type="pdf",
        file_path="/tmp/doc.pdf",
    )
    base.update(overrides)
    return base


async def test_create_persists_queued_job(repo: JobRepository) -> None:
    args = _job_args()
    created = await repo.create(**args)
    assert created.status is JobStatus.QUEUED
    assert created.job_id == args["job_id"]
    assert created.client_id == "tenant-1"
    assert created.file_type == "pdf"
    assert created.created_at == created.updated_at
    assert created.error_message is None


async def test_get_returns_stored_job(repo: JobRepository) -> None:
    args = _job_args()
    await repo.create(**args)
    fetched = await repo.get(args["job_id"])
    assert fetched is not None
    assert fetched.job_id == args["job_id"]
    assert fetched.job_type is JobType.INDEX_DOCUMENT


async def test_get_missing_returns_none(repo: JobRepository) -> None:
    assert await repo.get("ghost") is None


async def test_mark_running_updates_status_and_timestamp(repo: JobRepository) -> None:
    args = _job_args()
    created = await repo.create(**args)
    # Ensure the clock advances so updated_at actually moves.
    await asyncio.sleep(0.01)
    running = await repo.mark_running(args["job_id"])
    assert running.status is JobStatus.RUNNING
    assert running.updated_at > created.updated_at


async def test_mark_succeeded_clears_error(repo: JobRepository) -> None:
    args = _job_args()
    await repo.create(**args)
    await repo.mark_failed(args["job_id"], error_message="transient")
    ok = await repo.mark_succeeded(args["job_id"])
    assert ok.status is JobStatus.SUCCEEDED
    assert ok.error_message is None


async def test_mark_failed_records_error(repo: JobRepository) -> None:
    args = _job_args()
    await repo.create(**args)
    failed = await repo.mark_failed(args["job_id"], error_message="boom")
    assert failed.status is JobStatus.FAILED
    assert failed.error_message == "boom"


async def test_mark_failed_truncates_long_error(repo: JobRepository) -> None:
    args = _job_args()
    await repo.create(**args)
    failed = await repo.mark_failed(args["job_id"], error_message="x" * 5000)
    assert failed.error_message is not None
    assert len(failed.error_message) == 2048


async def test_transitions_on_missing_job_raise(repo: JobRepository) -> None:
    with pytest.raises(LookupError):
        await repo.mark_running("ghost")
    with pytest.raises(LookupError):
        await repo.mark_succeeded("ghost")
    with pytest.raises(LookupError):
        await repo.mark_failed("ghost", error_message="x")


async def test_delete_job_stores_nullable_file_path(repo: JobRepository) -> None:
    args = _job_args(job_type=JobType.DELETE_DOCUMENT, file_path=None, file_type="")
    created = await repo.create(**args)
    fetched = await repo.get(created.job_id)
    assert fetched is not None
    assert fetched.file_path is None
    assert fetched.file_type == ""
    assert fetched.job_type is JobType.DELETE_DOCUMENT
