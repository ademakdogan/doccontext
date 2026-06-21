from __future__ import annotations

import grpc

from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.services.index_service import IndexDocumentHandler


class DocContextServicer(pb_grpc.DocContextServicer):
    """Thin composition layer: one handler instance per RPC method.

    Handlers for the other three methods are added as they come online.
    Until then, the inherited base methods return UNIMPLEMENTED.
    """

    def __init__(self, *, index: IndexDocumentHandler) -> None:
        self._index = index

    async def IndexDocument(
        self, request: pb.IndexDocumentRequest, context: grpc.aio.ServicerContext
    ) -> pb.IndexDocumentResponse:
        return await self._index.handle(request, context)
