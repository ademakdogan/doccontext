from __future__ import annotations

from pathlib import Path

from doccontext.config import Settings, get_settings, reload_settings


def test_defaults_when_no_env(isolated_env) -> None:
    s = Settings()
    assert s.grpc_host == "0.0.0.0"
    assert s.grpc_port == 50051
    assert s.qdrant_host == "localhost"
    assert s.qdrant_port == 6333
    assert s.qdrant_collection_prefix == "doccontext"
    assert s.rabbitmq_user == "guest"
    assert s.postgres_db == "doccontext"
    assert s.embedding_provider == "minilm"
    assert s.vector_store_provider == "qdrant"
    assert s.chunk_size == 800
    assert s.chunk_overlap == 160
    assert s.llm_router_model == "openai/gpt-5-mini"
    assert s.llm_answer_model == "openai/gpt-5-mini"
    assert s.query_top_k_default == 5
    assert s.max_concurrent_queries == 10


def test_env_overrides(isolated_env) -> None:
    isolated_env.setenv("GRPC_PORT", "60000")
    isolated_env.setenv("EMBEDDING_PROVIDER", "bge-m3")
    isolated_env.setenv("VECTOR_STORE_PROVIDER", "weaviate")
    isolated_env.setenv("MAX_CONCURRENT_QUERIES", "25")
    isolated_env.setenv("LLM_ROUTER_MODEL", "anthropic/claude-sonnet-4.6")

    s = Settings()
    assert s.grpc_port == 60000
    assert s.embedding_provider == "bge-m3"
    assert s.vector_store_provider == "weaviate"
    assert s.max_concurrent_queries == 25
    assert s.llm_router_model == "anthropic/claude-sonnet-4.6"


def test_env_keys_are_case_insensitive(isolated_env) -> None:
    isolated_env.setenv("grpc_port", "7777")
    s = Settings()
    assert s.grpc_port == 7777


def test_postgres_dsn_builds_correctly(isolated_env) -> None:
    isolated_env.setenv("POSTGRES_USER", "u")
    isolated_env.setenv("POSTGRES_PASSWORD", "p")
    isolated_env.setenv("POSTGRES_HOST", "db.internal")
    isolated_env.setenv("POSTGRES_PORT", "5433")
    isolated_env.setenv("POSTGRES_DB", "ctx")
    s = Settings()
    assert s.postgres_dsn == "postgresql+asyncpg://u:p@db.internal:5433/ctx"


def test_rabbitmq_url_builds_correctly(isolated_env) -> None:
    isolated_env.setenv("RABBITMQ_USER", "u")
    isolated_env.setenv("RABBITMQ_PASSWORD", "p")
    isolated_env.setenv("RABBITMQ_HOST", "rmq.internal")
    isolated_env.setenv("RABBITMQ_PORT", "5673")
    isolated_env.setenv("RABBITMQ_VHOST", "/")
    s = Settings()
    assert s.rabbitmq_url == "amqp://u:p@rmq.internal:5673/"


def test_rabbitmq_url_adds_missing_slash_on_vhost(isolated_env) -> None:
    isolated_env.setenv("RABBITMQ_VHOST", "prod")
    s = Settings()
    assert s.rabbitmq_url.endswith(":5672/prod")


def test_qdrant_url_builds_correctly(isolated_env) -> None:
    isolated_env.setenv("QDRANT_HOST", "q.internal")
    isolated_env.setenv("QDRANT_PORT", "6334")
    s = Settings()
    assert s.qdrant_url == "http://q.internal:6334"


def test_log_paths_are_path_objects(isolated_env) -> None:
    s = Settings()
    for p in (
        s.log_dir,
        s.log_file_index_document,
        s.log_file_get_indexing_job_status,
        s.log_file_query_documents,
        s.log_file_delete_document,
        s.log_file_worker,
    ):
        assert isinstance(p, Path)


def test_get_settings_is_cached(isolated_env) -> None:
    a = get_settings()
    b = get_settings()
    assert a is b


def test_reload_settings_clears_cache(isolated_env) -> None:
    a = get_settings()
    isolated_env.setenv("GRPC_PORT", "12345")
    b = reload_settings()
    assert a is not b
    assert b.grpc_port == 12345


def test_extra_env_keys_are_ignored(isolated_env) -> None:
    isolated_env.setenv("DOCCONTEXT_UNKNOWN_FLAG", "x")
    # Should not raise.
    Settings()


def test_reads_env_file_when_present(isolated_env, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "GRPC_PORT=51000\nLLM_ANSWER_MODEL=openai/gpt-4o\n",
        encoding="utf-8",
    )
    s = Settings()
    assert s.grpc_port == 51000
    assert s.llm_answer_model == "openai/gpt-4o"
