from __future__ import annotations

import grpc

from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc
from doccontext.services.delete_service import DeleteDocumentHandler
from doccontext.services.index_service import IndexDocumentHandler
from doccontext.services.query_service import QueryDocumentsHandler
from doccontext.services.status_service import GetIndexingJobStatusHandler


class DocContextServicer(pb_grpc.DocContextServicer):
<<<<<<< HEAD
    """Thin composition layer: one handler instance per RPC method."""
=======
    """Thin composition layer: one handler instance per RPC method.

    QueryDocuments is added in a later commit; until then it inherits the
    gRPC UNIMPLEMENTED default.
    """
>>>>>>> 67d3ecb (feat(services): DeleteDocument gRPC handler)

    def __init__(
        self,
        *,
        index: IndexDocumentHandler,
        status: GetIndexingJobStatusHandler,
        delete: DeleteDocumentHandler,
<<<<<<< HEAD
        query: QueryDocumentsHandler,
=======
>>>>>>> 67d3ecb (feat(services): DeleteDocument gRPC handler)
    ) -> None:
        self._index = index
        self._status = status
        self._delete = delete
<<<<<<< HEAD
        self._query = query
=======
>>>>>>> 67d3ecb (feat(services): DeleteDocument gRPC handler)

    async def IndexDocument(
        self, request: pb.IndexDocumentRequest, context: grpc.aio.ServicerContext
    ) -> pb.IndexDocumentResponse:
        return await self._index.handle(request, context)

    async def GetIndexingJobStatus(
        self,
        request: pb.GetIndexingJobStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.GetIndexingJobStatusResponse:
        return await self._status.handle(request, context)

    async def DeleteDocument(
        self, request: pb.DeleteDocumentRequest, context: grpc.aio.ServicerContext
    ) -> pb.DeleteDocumentResponse:
        return await self._delete.handle(request, context)
<<<<<<< HEAD

    async def QueryDocuments(
        self, request: pb.QueryDocumentsRequest, context: grpc.aio.ServicerContext
    ) -> pb.QueryDocumentsResponse:
        return await self._query.handle(request, context)
=======
>>>>>>> 67d3ecb (feat(services): DeleteDocument gRPC handler)
