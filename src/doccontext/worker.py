"""CLI entrypoint for the document_jobs consumer.

Wires the default embedder / vector store / queue consumer / chunker / job
repository together and blocks until cancelled.

Run with: ``uv run python -m doccontext.worker``.
"""

from __future__ import annotations

import asyncio

from doccontext.chunking import default_chunker
from doccontext.config import get_settings
from doccontext.embeddings import get_embedder
from doccontext.logging_config import LogChannel, configure_logging, get_logger
from doccontext.queue import get_queue_consumer
from doccontext.repositories import JobRepository, bootstrap_schema, create_engine
from doccontext.vector_stores import get_vector_store
from doccontext.workers import DocumentWorker, run_worker


async def main() -> None:
    configure_logging()
    log = get_logger(LogChannel.WORKER)
    settings = get_settings()

    engine = create_engine(settings)
    await bootstrap_schema(engine)
    repo = JobRepository(engine)

    consumer = get_queue_consumer(settings)
    worker = DocumentWorker(
        repository=repo,
        vector_store=get_vector_store(settings),
        embedder=get_embedder(settings),
        chunker=default_chunker(settings),
    )

    log.info(
        "worker starting",
        queue=settings.rabbitmq_document_jobs_queue,
        embedding_provider=settings.embedding_provider,
        vector_store_provider=settings.vector_store_provider,
    )
    try:
        await run_worker(consumer=consumer, worker=worker, settings=settings)
    finally:
        await consumer.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
