from __future__ import annotations

import time

import grpc

from doccontext.logging_config import LogChannel, get_logger
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.repositories.job import JobRepository
from doccontext.services.converters import status_to_proto


class GetIndexingJobStatusHandler:
    """Reads a job's status from the repository and returns it verbatim."""

    def __init__(self, *, repository: JobRepository) -> None:
        self._repo = repository
        self._log = get_logger(LogChannel.GET_INDEXING_JOB_STATUS)

    async def handle(
        self,
        request: pb.GetIndexingJobStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.GetIndexingJobStatusResponse:
        start = time.monotonic()
        if not request.job_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "job_id is required")

        job = await self._repo.get(request.job_id)
        if job is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"job {request.job_id} not found")

        self._log.info(
            "get_indexing_job_status ok",
            job_id=job.job_id,
            status=str(job.status),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return pb.GetIndexingJobStatusResponse(
            job_id=job.job_id,
            document_id=job.document_id,
            status=status_to_proto(job.status),
            error_message=job.error_message or "",
        )
