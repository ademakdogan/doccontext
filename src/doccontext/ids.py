from __future__ import annotations

import uuid

# Stable namespace used to derive deterministic chunk IDs from (document, index).
# Derived once and baked in so re-indexing the same document overwrites the same
# vector points (upserts) instead of piling up duplicates.
_CHUNK_NAMESPACE = uuid.UUID("1ff9d3e0-d3d0-4c2c-9a50-4c07f1b6fbb5")


def new_id() -> str:
    """Fresh uuid4 for job / document / session identifiers."""
    return str(uuid.uuid4())


def new_job_id() -> str:
    return new_id()


def new_document_id() -> str:
    return new_id()


def chunk_id_for(document_id: str, chunk_index: int) -> str:
    """Deterministic chunk id so re-indexing upserts rather than duplicates."""
    return str(uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:{chunk_index}"))
