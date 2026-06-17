from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from doccontext.config import Settings, get_settings
from doccontext.models.job import Job, JobStatus, JobType


class _Base(DeclarativeBase):
    pass


class _JobORM(_Base):
    __tablename__ = "indexing_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    corpus_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _to_domain(row: _JobORM) -> Job:
    return Job(
        job_id=row.job_id,
        job_type=JobType(row.job_type),
        status=JobStatus(row.status),
        client_id=row.client_id,
        corpus_id=row.corpus_id,
        document_id=row.document_id,
        file_type=row.file_type,
        file_path=row.file_path,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    return create_async_engine(s.postgres_dsn, pool_pre_ping=True)


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Create the indexing_jobs table if it doesn't exist.

    We keep the schema in code rather than Alembic since there is only one
    table today. Swap in Alembic when migrations become real.
    """
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)


class JobRepository:
    """Async persistence for job lifecycle state."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    def _session(self) -> AsyncSession:
        return self._sessionmaker()

    async def create(
        self,
        *,
        job_id: str,
        job_type: JobType,
        client_id: str,
        corpus_id: str,
        document_id: str,
        file_type: str = "",
        file_path: str | None = None,
    ) -> Job:
        now = datetime.now(UTC)
        row = _JobORM(
            job_id=job_id,
            job_type=str(job_type),
            status=str(JobStatus.QUEUED),
            client_id=client_id,
            corpus_id=corpus_id,
            document_id=document_id,
            file_type=file_type,
            file_path=file_path,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        async with self._session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _to_domain(row)

    async def get(self, job_id: str) -> Job | None:
        async with self._session() as session:
            row = await session.get(_JobORM, job_id)
            return _to_domain(row) if row is not None else None

    async def mark_running(self, job_id: str) -> Job:
        return await self._transition(job_id, status=JobStatus.RUNNING)

    async def mark_succeeded(self, job_id: str) -> Job:
        return await self._transition(
            job_id, status=JobStatus.SUCCEEDED, error_message=None
        )

    async def mark_failed(self, job_id: str, *, error_message: str) -> Job:
        return await self._transition(
            job_id, status=JobStatus.FAILED, error_message=error_message[:2048]
        )

    async def _transition(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error_message: str | None = ...,  # type: ignore[assignment]
    ) -> Job:
        async with self._session() as session:
            row = await session.get(_JobORM, job_id)
            if row is None:
                raise LookupError(f"job {job_id} not found")
            row.status = str(status)
            row.updated_at = datetime.now(UTC)
            if error_message is not Ellipsis:
                row.error_message = error_message
            await session.commit()
            await session.refresh(row)
            return _to_domain(row)
