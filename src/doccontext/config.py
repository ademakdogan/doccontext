from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
    qdrant_collection_prefix: str = "doccontext"

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_vhost: str = "/"
    rabbitmq_document_jobs_queue: str = "document_jobs"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "doccontext"
    postgres_password: str = "doccontext"
    postgres_db: str = "doccontext"

    embedding_provider: str = "minilm"
    vector_store_provider: str = "qdrant"

    chunk_size: int = 800
    chunk_overlap: int = 160

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_router_model: str = "openai/gpt-5-mini"
    llm_answer_model: str = "openai/gpt-5-mini"

    query_top_k_default: int = 5
    max_concurrent_queries: int = 10

    log_level: str = "INFO"
    log_dir: Path = Path("./logs")
    log_file_index_document: Path = Path("./logs/index_document.log")
    log_file_get_indexing_job_status: Path = Path("./logs/get_indexing_job_status.log")
    log_file_query_documents: Path = Path("./logs/query_documents.log")
    log_file_delete_document: Path = Path("./logs/delete_document.log")
    log_file_worker: Path = Path("./logs/document_worker.log")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbitmq_url(self) -> str:
        vhost = self.rabbitmq_vhost if self.rabbitmq_vhost.startswith("/") else f"/{self.rabbitmq_vhost}"
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{vhost}"
        )

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
