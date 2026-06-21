"""Proto ↔ domain enum conversions for the gRPC service layer."""

from __future__ import annotations

from doccontext.models.job import JobStatus, JobType
from doccontext.proto_gen import doccontext_pb2 as pb


# --- file type ---------------------------------------------------------------


_PROTO_FILE_TYPE_TO_STR: dict[int, str] = {
    pb.PDF: "pdf",
    pb.TXT: "txt",
    pb.MD: "md",
}


def file_type_to_str(proto_value: int) -> str:
    try:
        return _PROTO_FILE_TYPE_TO_STR[proto_value]
    except KeyError as e:
        raise ValueError(f"unsupported or unspecified FileType: {proto_value}") from e


# --- job status --------------------------------------------------------------


_DOMAIN_STATUS_TO_PROTO: dict[JobStatus, int] = {
    JobStatus.QUEUED: pb.QUEUED,
    JobStatus.RUNNING: pb.RUNNING,
    JobStatus.SUCCEEDED: pb.SUCCEEDED,
    JobStatus.FAILED: pb.FAILED,
}


def status_to_proto(status: JobStatus) -> int:
    return _DOMAIN_STATUS_TO_PROTO[status]


# --- job type ----------------------------------------------------------------


_DOMAIN_JOB_TYPE_TO_PROTO: dict[JobType, int] = {
    JobType.INDEX_DOCUMENT: pb.INDEX_DOCUMENT,
    JobType.DELETE_DOCUMENT: pb.DELETE_DOCUMENT,
}


def job_type_to_proto(job_type: JobType) -> int:
    return _DOMAIN_JOB_TYPE_TO_PROTO[job_type]


# --- query route -------------------------------------------------------------


_ROUTE_TO_PROTO: dict[str, int] = {
    "SECTION": pb.SECTION,
    "FULL_DOC": pb.FULL_DOC,
}


def query_route_to_proto(route: str) -> int:
    try:
        return _ROUTE_TO_PROTO[route]
    except KeyError as e:
        raise ValueError(f"unsupported QueryRoute: {route!r}") from e
