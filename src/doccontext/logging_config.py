from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

from doccontext.config import Settings, get_settings


class LogChannel(StrEnum):
    INDEX_DOCUMENT = "index_document"
    GET_INDEXING_JOB_STATUS = "get_indexing_job_status"
    QUERY_DOCUMENTS = "query_documents"
    DELETE_DOCUMENT = "delete_document"
    WORKER = "document_worker"


_CHANNEL_TO_SETTING: dict[LogChannel, str] = {
    LogChannel.INDEX_DOCUMENT: "log_file_index_document",
    LogChannel.GET_INDEXING_JOB_STATUS: "log_file_get_indexing_job_status",
    LogChannel.QUERY_DOCUMENTS: "log_file_query_documents",
    LogChannel.DELETE_DOCUMENT: "log_file_delete_document",
    LogChannel.WORKER: "log_file_worker",
}

_LOGGER_PREFIX = "doccontext.channels"

_configured = False


def channel_logger_name(channel: LogChannel) -> str:
    return f"{_LOGGER_PREFIX}.{channel.value}"


def _rename_timestamp_to_created_at(_: Any, __: str, event_dict: EventDict) -> EventDict:
    if "timestamp" in event_dict:
        event_dict["createdAt"] = event_dict.pop("timestamp")
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _rename_timestamp_to_created_at,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(sort_keys=True),
    ]


def _file_handler(path: Path, level: int) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._doccontext_channel = True  # type: ignore[attr-defined]
    return handler


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog + per-channel stdlib loggers.

    Each gRPC method / worker gets its own named stdlib logger bound to its
    own file handler, so lines land in the right file. All handlers share
    the same JSON renderer with UTC ``createdAt`` timestamps.
    """
    global _configured
    s = settings or get_settings()

    s.log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.getLevelNamesMapping().get(s.log_level.upper(), logging.INFO)

    for channel, attr in _CHANNEL_TO_SETTING.items():
        logger_name = channel_logger_name(channel)
        stdlib_logger = logging.getLogger(logger_name)
        stdlib_logger.setLevel(level)
        stdlib_logger.propagate = False
        for existing in list(stdlib_logger.handlers):
            if getattr(existing, "_doccontext_channel", False):
                stdlib_logger.removeHandler(existing)
        stdlib_logger.addHandler(_file_handler(getattr(s, attr), level))

    structlog.configure(
        processors=_shared_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    _configured = True


def get_logger(channel: LogChannel, **bound: Any) -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    logger = structlog.get_logger(channel_logger_name(channel))
    return logger.bind(channel=channel.value, **bound)
