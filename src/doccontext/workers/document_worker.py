from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from doccontext.chunking.base import Chunk, Chunker
from doccontext.config import Settings, get_settings
from doccontext.embeddings.base import Embedder
from doccontext.extractors import extract_text
from doccontext.ids import chunk_id_for
from doccontext.logging_config import LogChannel, get_logger
from doccontext.models.chunk import StoredChunk
from doccontext.models.job import JobType
from doccontext.queue.base import QueueConsumer
from doccontext.repositories.job import JobRepository
from doccontext.vector_stores.base import VectorStore
from doccontext.workers.envelope import JobEnvelope


class DocumentWorker:
    """Handles INDEX_DOCUMENT / DELETE_DOCUMENT job envelopes end-to-end.

    The worker owns the job-status lifecycle: it moves QUEUED → RUNNING
    before doing any work and SUCCEEDED / FAILED afterwards. Failures are
    re-raised so the queue layer can drop the poison message.
    """

    def __init__(
        self,
        *,
        repository: JobRepository,
        vector_store: VectorStore,
        embedder: Embedder,
        chunker: Chunker,
    ) -> None:
        self._repo = repository
        self._vector_store = vector_store
        self._embedder = embedder
        self._chunker = chunker
        self._log = get_logger(LogChannel.WORKER)

    async def handle(self, payload: Mapping[str, Any]) -> None:
        env = JobEnvelope.from_payload(payload)
        log = self._log.bind(
            job_id=env.job_id,
            job_type=str(env.job_type),
            client_id=env.client_id,
            corpus_id=env.corpus_id,
            document_id=env.document_id,
        )
        start = time.monotonic()
        await self._repo.mark_running(env.job_id)
        try:
            if env.job_type is JobType.INDEX_DOCUMENT:
                chunk_count = await self._handle_index(env)
                log.info(
                    "index_document ok",
                    chunk_count=chunk_count,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    file_type=env.file_type,
                )
            elif env.job_type is JobType.DELETE_DOCUMENT:
                deleted = await self._handle_delete(env)
                log.info(
                    "delete_document ok",
                    deleted_chunks=deleted,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            else:  # pragma: no cover — StrEnum coercion catches this earlier
                raise ValueError(f"unsupported job_type: {env.job_type}")
            await self._repo.mark_succeeded(env.job_id)
        except Exception as exc:
            log.exception(
                "job failed",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            await self._repo.mark_failed(env.job_id, error_message=str(exc))
            raise

    async def _handle_index(self, env: JobEnvelope) -> int:
        if not env.file_path:
            raise ValueError("INDEX_DOCUMENT envelope missing file_path")
        path = Path(env.file_path)

        text = await asyncio.to_thread(extract_text, path, env.file_type)
        chunks: list[Chunk] = list(self._chunker.chunk(text))
        if not chunks:
            return 0

        vectors = await asyncio.to_thread(
            self._embedder.embed, [c.text for c in chunks]
        )
        # Make sure the collection exists with the embedder's dimensionality
        # before the first upsert — idempotent after the first run.
        await asyncio.to_thread(self._vector_store.ensure_collection, self._embedder.dim)

        stored = [
            StoredChunk(
                chunk_id=chunk_id_for(env.document_id, c.chunk_index),
                document_id=env.document_id,
                corpus_id=env.corpus_id,
                client_id=env.client_id,
                chunk_index=c.chunk_index,
                char_start=c.char_start,
                char_end=c.char_end,
                text=c.text,
                file_type=env.file_type,
                vector=list(v),
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        return await asyncio.to_thread(self._vector_store.upsert, stored)

    async def _handle_delete(self, env: JobEnvelope) -> int:
        return await asyncio.to_thread(
            self._vector_store.delete_by_document,
            client_id=env.client_id,
            document_id=env.document_id,
        )


async def run_worker(
    *,
    consumer: QueueConsumer,
    worker: DocumentWorker,
    settings: Settings | None = None,
) -> None:
    """Block forever, dispatching document_jobs messages to ``worker``."""
    s = settings or get_settings()
    await consumer.consume(
        queue=s.rabbitmq_document_jobs_queue,
        handler=worker.handle,
        prefetch=1,
    )
