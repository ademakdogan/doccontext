from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobType(StrEnum):
    INDEX_DOCUMENT = "INDEX_DOCUMENT"
    DELETE_DOCUMENT = "DELETE_DOCUMENT"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Job:
    """Domain view of a queued document job. Mirrors the proto JobStatus/JobType
    values so we can translate without a lookup table."""

    job_id: str
    job_type: JobType
    status: JobStatus
    client_id: str
    corpus_id: str
    document_id: str
    file_type: str
    file_path: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
