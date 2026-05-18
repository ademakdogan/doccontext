from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FileType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILE_TYPE_UNSPECIFIED: _ClassVar[FileType]
    PDF: _ClassVar[FileType]
    TXT: _ClassVar[FileType]
    MD: _ClassVar[FileType]

class JobType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_TYPE_UNSPECIFIED: _ClassVar[JobType]
    INDEX_DOCUMENT: _ClassVar[JobType]
    DELETE_DOCUMENT: _ClassVar[JobType]

class JobStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STATUS_UNSPECIFIED: _ClassVar[JobStatus]
    QUEUED: _ClassVar[JobStatus]
    RUNNING: _ClassVar[JobStatus]
    SUCCEEDED: _ClassVar[JobStatus]
    FAILED: _ClassVar[JobStatus]

class QueryRoute(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    QUERY_ROUTE_UNSPECIFIED: _ClassVar[QueryRoute]
    SECTION: _ClassVar[QueryRoute]
    FULL_DOC: _ClassVar[QueryRoute]
FILE_TYPE_UNSPECIFIED: FileType
PDF: FileType
TXT: FileType
MD: FileType
JOB_TYPE_UNSPECIFIED: JobType
INDEX_DOCUMENT: JobType
DELETE_DOCUMENT: JobType
JOB_STATUS_UNSPECIFIED: JobStatus
QUEUED: JobStatus
RUNNING: JobStatus
SUCCEEDED: JobStatus
FAILED: JobStatus
QUERY_ROUTE_UNSPECIFIED: QueryRoute
SECTION: QueryRoute
FULL_DOC: QueryRoute

class Citation(_message.Message):
    __slots__ = ("document_id", "corpus_id", "chunk_index", "char_start", "char_end", "score")
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    CHUNK_INDEX_FIELD_NUMBER: _ClassVar[int]
    CHAR_START_FIELD_NUMBER: _ClassVar[int]
    CHAR_END_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    corpus_id: str
    chunk_index: int
    char_start: int
    char_end: int
    score: float
    def __init__(self, document_id: _Optional[str] = ..., corpus_id: _Optional[str] = ..., chunk_index: _Optional[int] = ..., char_start: _Optional[int] = ..., char_end: _Optional[int] = ..., score: _Optional[float] = ...) -> None: ...

class HistoryMessage(_message.Message):
    __slots__ = ("role", "content")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: str
    def __init__(self, role: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class IndexDocumentRequest(_message.Message):
    __slots__ = ("document_id", "client_id", "user_id", "corpus_id", "file_type", "storage_path", "metadata")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    FILE_TYPE_FIELD_NUMBER: _ClassVar[int]
    STORAGE_PATH_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    client_id: str
    user_id: str
    corpus_id: str
    file_type: FileType
    storage_path: str
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, document_id: _Optional[str] = ..., client_id: _Optional[str] = ..., user_id: _Optional[str] = ..., corpus_id: _Optional[str] = ..., file_type: _Optional[_Union[FileType, str]] = ..., storage_path: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class IndexDocumentResponse(_message.Message):
    __slots__ = ("job_id", "status")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: JobStatus
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[_Union[JobStatus, str]] = ...) -> None: ...

class GetIndexingJobStatusRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class GetIndexingJobStatusResponse(_message.Message):
    __slots__ = ("job_id", "document_id", "status", "error_message")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    document_id: str
    status: JobStatus
    error_message: str
    def __init__(self, job_id: _Optional[str] = ..., document_id: _Optional[str] = ..., status: _Optional[_Union[JobStatus, str]] = ..., error_message: _Optional[str] = ...) -> None: ...

class QueryDocumentsRequest(_message.Message):
    __slots__ = ("client_id", "user_id", "chat_session_id", "corpus_ids", "prompt", "history_window", "top_k", "history")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CHAT_SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CORPUS_IDS_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    HISTORY_WINDOW_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    user_id: str
    chat_session_id: str
    corpus_ids: _containers.RepeatedScalarFieldContainer[str]
    prompt: str
    history_window: int
    top_k: int
    history: _containers.RepeatedCompositeFieldContainer[HistoryMessage]
    def __init__(self, client_id: _Optional[str] = ..., user_id: _Optional[str] = ..., chat_session_id: _Optional[str] = ..., corpus_ids: _Optional[_Iterable[str]] = ..., prompt: _Optional[str] = ..., history_window: _Optional[int] = ..., top_k: _Optional[int] = ..., history: _Optional[_Iterable[_Union[HistoryMessage, _Mapping]]] = ...) -> None: ...

class QueryDocumentsResponse(_message.Message):
    __slots__ = ("answer", "used_route", "citations", "confidence")
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    USED_ROUTE_FIELD_NUMBER: _ClassVar[int]
    CITATIONS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    answer: str
    used_route: QueryRoute
    citations: _containers.RepeatedCompositeFieldContainer[Citation]
    confidence: float
    def __init__(self, answer: _Optional[str] = ..., used_route: _Optional[_Union[QueryRoute, str]] = ..., citations: _Optional[_Iterable[_Union[Citation, _Mapping]]] = ..., confidence: _Optional[float] = ...) -> None: ...

class DeleteDocumentRequest(_message.Message):
    __slots__ = ("document_id", "client_id", "user_id")
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    client_id: str
    user_id: str
    def __init__(self, document_id: _Optional[str] = ..., client_id: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class DeleteDocumentResponse(_message.Message):
    __slots__ = ("job_id", "status")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: JobStatus
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[_Union[JobStatus, str]] = ...) -> None: ...
