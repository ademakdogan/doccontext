from __future__ import annotations

import time

import grpc

from doccontext.config import Settings, get_settings
from doccontext.ids import new_job_id
from doccontext.logging_config import LogChannel, get_logger
from doccontext.models.job import JobStatus, JobType
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.queue.base import QueuePublisher
from doccontext.repositories.job import JobRepository
from doccontext.services.converters import status_to_proto
from doccontext.workers.envelope import JobEnvelope


class DeleteDocumentHandler:
    """Queues a DELETE_DOCUMENT envelope. The worker does the vector-store wipe."""

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
        self._log = get_logger(LogChannel.DELETE_DOCUMENT)

    async def handle(
        self,
        request: pb.DeleteDocumentRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.DeleteDocumentResponse:
        start = time.monotonic()

        if not request.client_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "client_id is required")
        if not request.document_id:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "document_id is required"
            )

        job_id = new_job_id()
        log = self._log.bind(
            job_id=job_id,
            document_id=request.document_id,
            client_id=request.client_id,
            user_id=request.user_id,
        )

        # corpus_id is not part of the proto for DELETE because a document can
        # only belong to one corpus, but the repo column is NOT NULL — store
        # an empty string and let the worker filter on (client_id, document_id).
        await self._repo.create(
            job_id=job_id,
            job_type=JobType.DELETE_DOCUMENT,
            client_id=request.client_id,
            corpus_id="",
            document_id=request.document_id,
            file_type="",
            file_path=None,
        )

        envelope = JobEnvelope(
            job_id=job_id,
            job_type=JobType.DELETE_DOCUMENT,
            client_id=request.client_id,
            corpus_id="",
            document_id=request.document_id,
            file_type="",
            file_path=None,
        )
        await self._publisher.publish(
            queue=self._settings.rabbitmq_document_jobs_queue,
            payload=envelope.to_payload(),
        )

        log.info(
            "delete_document queued",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

        return pb.DeleteDocumentResponse(
            job_id=job_id,
            status=status_to_proto(JobStatus.QUEUED),
        )
