from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from doccontext.config import reload_settings
from doccontext.logging_config import (
    LogChannel,
    channel_logger_name,
    configure_logging,
    get_logger,
)

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


@pytest.fixture
def log_env(isolated_env, tmp_path):
    isolated_env.setenv("LOG_DIR", str(tmp_path / "logs"))
    isolated_env.setenv("LOG_FILE_INDEX_DOCUMENT", str(tmp_path / "logs" / "index_document.log"))
    isolated_env.setenv(
        "LOG_FILE_GET_INDEXING_JOB_STATUS", str(tmp_path / "logs" / "get_indexing_job_status.log")
    )
    isolated_env.setenv("LOG_FILE_QUERY_DOCUMENTS", str(tmp_path / "logs" / "query_documents.log"))
    isolated_env.setenv("LOG_FILE_DELETE_DOCUMENT", str(tmp_path / "logs" / "delete_document.log"))
    isolated_env.setenv("LOG_FILE_WORKER", str(tmp_path / "logs" / "document_worker.log"))
    configure_logging(reload_settings())
    yield tmp_path / "logs"
    logging.shutdown()


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_log_is_valid_json_with_expected_fields(log_env) -> None:
    get_logger(LogChannel.INDEX_DOCUMENT, job_id="j1").info(
        "indexing_started", document_id="d1", file_type="pdf"
    )
    logging.shutdown()

    records = _read_lines(log_env / "index_document.log")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "indexing_started"
    assert rec["channel"] == "index_document"
    assert rec["job_id"] == "j1"
    assert rec["document_id"] == "d1"
    assert rec["file_type"] == "pdf"
    assert rec["level"] == "info"


def test_timestamp_is_utc_iso_and_named_created_at(log_env) -> None:
    get_logger(LogChannel.QUERY_DOCUMENTS).info("query_ok")
    logging.shutdown()

    rec = _read_lines(log_env / "query_documents.log")[0]
    assert "timestamp" not in rec
    assert "createdAt" in rec
    assert _ISO_UTC.match(rec["createdAt"]), rec["createdAt"]


def test_channels_are_isolated_to_their_own_files(log_env) -> None:
    get_logger(LogChannel.INDEX_DOCUMENT).info("idx_event")
    get_logger(LogChannel.QUERY_DOCUMENTS).info("qry_event")
    get_logger(LogChannel.DELETE_DOCUMENT).info("del_event")
    get_logger(LogChannel.WORKER).info("wrk_event")
    get_logger(LogChannel.GET_INDEXING_JOB_STATUS).info("sts_event")
    logging.shutdown()

    assert [r["event"] for r in _read_lines(log_env / "index_document.log")] == ["idx_event"]
    assert [r["event"] for r in _read_lines(log_env / "query_documents.log")] == ["qry_event"]
    assert [r["event"] for r in _read_lines(log_env / "delete_document.log")] == ["del_event"]
    assert [r["event"] for r in _read_lines(log_env / "document_worker.log")] == ["wrk_event"]
    assert [r["event"] for r in _read_lines(log_env / "get_indexing_job_status.log")] == ["sts_event"]


def test_query_documents_carries_llm_telemetry_fields(log_env) -> None:
    """QueryDocuments log lines must be able to carry the agreed telemetry keys."""
    get_logger(
        LogChannel.QUERY_DOCUMENTS,
        client_id="c1",
        user_id="u1",
        chat_session_id="s1",
    ).info(
        "query_completed",
        duration_ms=432,
        model_router="openai/gpt-5-mini",
        model_answer="openai/gpt-5-mini",
        input_tokens=1200,
        output_tokens=87,
        route="SECTION",
        top_k=5,
        corpus_ids=["c-1", "c-2"],
        confidence=0.92,
    )
    logging.shutdown()

    rec = _read_lines(log_env / "query_documents.log")[0]
    for key in (
        "duration_ms",
        "model_router",
        "model_answer",
        "input_tokens",
        "output_tokens",
        "route",
        "top_k",
        "corpus_ids",
        "confidence",
        "client_id",
        "user_id",
        "chat_session_id",
    ):
        assert key in rec, f"missing {key}"


def test_configure_is_idempotent(log_env) -> None:
    configure_logging(reload_settings())
    configure_logging(reload_settings())
    stdlib_logger = logging.getLogger(channel_logger_name(LogChannel.INDEX_DOCUMENT))
    channel_handlers = [h for h in stdlib_logger.handlers if getattr(h, "_doccontext_channel", False)]
    assert len(channel_handlers) == 1


def test_log_directory_is_created(isolated_env, tmp_path) -> None:
    target = tmp_path / "nested" / "logs"
    isolated_env.setenv("LOG_DIR", str(target))
    isolated_env.setenv("LOG_FILE_INDEX_DOCUMENT", str(target / "index_document.log"))
    isolated_env.setenv("LOG_FILE_GET_INDEXING_JOB_STATUS", str(target / "status.log"))
    isolated_env.setenv("LOG_FILE_QUERY_DOCUMENTS", str(target / "query.log"))
    isolated_env.setenv("LOG_FILE_DELETE_DOCUMENT", str(target / "delete.log"))
    isolated_env.setenv("LOG_FILE_WORKER", str(target / "worker.log"))
    configure_logging(reload_settings())
    assert target.is_dir()
    logging.shutdown()


def test_exception_is_rendered_with_traceback(log_env) -> None:
    log = get_logger(LogChannel.WORKER)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("job_failed")
    logging.shutdown()

    rec = _read_lines(log_env / "document_worker.log")[0]
    assert rec["event"] == "job_failed"
    assert "exception" in rec
    assert "RuntimeError: boom" in rec["exception"]
