from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from doccontext.config import reload_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Set env vars for a test and reload the cached Settings before + after."""
    reload_settings()
    try:
        yield monkeypatch
    finally:
        reload_settings()


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[pytest.MonkeyPatch]:
    """Start from a clean slate: clear every DOCCONTEXT-relevant env var, chdir to tmp_path."""
    for key in list(os.environ.keys()):
        if key.startswith(
            (
                "GRPC_",
                "QDRANT_",
                "RABBITMQ_",
                "POSTGRES_",
                "EMBEDDING_",
                "VECTOR_STORE_",
                "CHUNK_",
                "OPENROUTER_",
                "LLM_",
                "QUERY_",
                "MAX_CONCURRENT_",
                "LOG_",
            )
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    reload_settings()
    try:
        yield monkeypatch
    finally:
        reload_settings()
