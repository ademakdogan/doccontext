from __future__ import annotations

import time

import grpc

from doccontext.config import Settings, get_settings
from doccontext.ids import new_document_id, new_job_id
from doccontext.logging_config import LogChannel, get_logger
from doccontext.models.job import JobStatus, JobType
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.queue.base import QueuePublisher
from doccontext.repositories.job import JobRepository
from doccontext.services.converters import file_type_to_str, status_to_proto
from doccontext.workers.envelope import JobEnvelope


class IndexDocumentHandler:
    """Creates a QUEUED job row and publishes an INDEX_DOCUMENT envelope.

    The actual work — extract → chunk → embed → upsert — happens inside the
    worker. The gRPC method is intentionally fast and side-effect-light so
    callers can fire-and-forget.
    """

    def __init__(
        self,
        *,
        repository: JobRepository,
        publisher: QueuePublisher,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repository
        self._publisher = publisher
        self._settings = settings or get_settings()
        self._log = get_logger(LogChannel.INDEX_DOCUMENT)

    async def handle(
        self,
        request: pb.IndexDocumentRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.IndexDocumentResponse:
        start = time.monotonic()

        if not request.client_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "client_id is required")
        if not request.corpus_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "corpus_id is required")
        if not request.storage_path:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "storage_path is required")

        try:
            file_type = file_type_to_str(request.file_type)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))

        job_id = new_job_id()
        document_id = request.document_id or new_document_id()

        log = self._log.bind(
            job_id=job_id,
            document_id=document_id,
            client_id=request.client_id,
            user_id=request.user_id,
            corpus_id=request.corpus_id,
            file_type=file_type,
        )

        await self._repo.create(
            job_id=job_id,
            job_type=JobType.INDEX_DOCUMENT,
            client_id=request.client_id,
            corpus_id=request.corpus_id,
            document_id=document_id,
            file_type=file_type,
            file_path=request.storage_path,
        )

        envelope = JobEnvelope(
            job_id=job_id,
            job_type=JobType.INDEX_DOCUMENT,
            client_id=request.client_id,
            corpus_id=request.corpus_id,
            document_id=document_id,
            file_type=file_type,
            file_path=request.storage_path,
        )
        await self._publisher.publish(
            queue=self._settings.rabbitmq_document_jobs_queue,
            payload=envelope.to_payload(),
        )

        log.info(
            "index_document queued",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

        return pb.IndexDocumentResponse(
            job_id=job_id,
            status=status_to_proto(JobStatus.QUEUED),
        )
