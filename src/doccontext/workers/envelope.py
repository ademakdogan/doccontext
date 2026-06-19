from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from doccontext.models.job import JobType


class MalformedJobEnvelope(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    """Wire format for messages on the document_jobs queue."""

    job_id: str
    job_type: JobType
    client_id: str
    corpus_id: str
    document_id: str
    file_type: str
    file_path: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "JobEnvelope":
        try:
            raw_type = payload["job_type"]
            return cls(
                job_id=str(payload["job_id"]),
                job_type=JobType(raw_type),
                client_id=str(payload["client_id"]),
                corpus_id=str(payload["corpus_id"]),
                document_id=str(payload["document_id"]),
                file_type=str(payload.get("file_type") or ""),
                file_path=(
                    str(payload["file_path"])
                    if payload.get("file_path")
                    else None
                ),
            )
        except (KeyError, ValueError) as exc:
            raise MalformedJobEnvelope(
                f"payload is not a valid job envelope: {exc}"
            ) from exc

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": str(self.job_type),
            "client_id": self.client_id,
            "corpus_id": self.corpus_id,
            "document_id": self.document_id,
            "file_type": self.file_type,
            "file_path": self.file_path,
        }
