"""gRPC server entrypoint.

Wires the minimal set of handlers currently implemented and serves them on
``GRPC_HOST:GRPC_PORT``. Run with ``uv run python -m doccontext.server``.
"""

from __future__ import annotations

import asyncio
import signal

import grpc

from doccontext.config import get_settings
from doccontext.embeddings.factory import get_embedder
from doccontext.llm.openrouter import OpenRouterClient
from doccontext.logging_config import LogChannel, configure_logging, get_logger
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.queue import get_queue_publisher
from doccontext.repositories import JobRepository, bootstrap_schema, create_engine
from doccontext.services.delete_service import DeleteDocumentHandler
from doccontext.services.index_service import IndexDocumentHandler
from doccontext.services.query_service import QueryDocumentsHandler
from doccontext.services.servicer import DocContextServicer
from doccontext.services.status_service import GetIndexingJobStatusHandler
from doccontext.vector_stores.factory import get_vector_store


async def serve() -> None:
    configure_logging()
    log = get_logger(LogChannel.INDEX_DOCUMENT, component="server")
    settings = get_settings()

    engine = create_engine(settings)
    await bootstrap_schema(engine)
    repo = JobRepository(engine)
    publisher = get_queue_publisher(settings)
    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings)
    llm = OpenRouterClient(settings)

    servicer = DocContextServicer(
        index=IndexDocumentHandler(
            repository=repo, publisher=publisher, settings=settings
        ),
        status=GetIndexingJobStatusHandler(repository=repo),
        delete=DeleteDocumentHandler(
            repository=repo, publisher=publisher, settings=settings
        ),
<<<<<<< HEAD
        query=QueryDocumentsHandler(
            embedder=embedder,
            vector_store=vector_store,
            llm=llm,
            settings=settings,
        ),
=======
>>>>>>> 67d3ecb (feat(services): DeleteDocument gRPC handler)
    )

    server = grpc.aio.server()
    pb_grpc.add_DocContextServicer_to_server(servicer, server)
    listen = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen)

    await server.start()
    log.info("server listening", address=listen)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    log.info("server stopping")
    await server.stop(grace=5.0)
    await publisher.close()
    await llm.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(serve())
