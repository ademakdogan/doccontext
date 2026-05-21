from __future__ import annotations

import socket

import pytest

from doccontext.config import get_settings

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def test_qdrant_port_is_reachable() -> None:
    s = get_settings()
    assert _port_open(s.qdrant_host, s.qdrant_port), (
        f"Qdrant not reachable at {s.qdrant_host}:{s.qdrant_port} — "
        "bring it up with `docker compose up -d qdrant`"
    )


def test_rabbitmq_port_is_reachable() -> None:
    s = get_settings()
    assert _port_open(s.rabbitmq_host, s.rabbitmq_port), (
        f"RabbitMQ not reachable at {s.rabbitmq_host}:{s.rabbitmq_port} — "
        "bring it up with `docker compose up -d rabbitmq`"
    )


def test_postgres_port_is_reachable() -> None:
    s = get_settings()
    assert _port_open(s.postgres_host, s.postgres_port), (
        f"Postgres not reachable at {s.postgres_host}:{s.postgres_port} — "
        "bring it up with `docker compose up -d postgres`"
    )
