from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from doccontext.config import Settings
from doccontext.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher

pytestmark = pytest.mark.integration


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_rabbitmq(s: Settings) -> None:
    if not _port_open(s.rabbitmq_host, s.rabbitmq_port):
        pytest.skip(
            f"RabbitMQ not reachable at {s.rabbitmq_host}:{s.rabbitmq_port} — "
            "bring it up with `docker compose up -d rabbitmq`"
        )


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    _require_rabbitmq(s)
    return s


@pytest.fixture
async def queue_name(settings: Settings) -> AsyncIterator[str]:
    """Generate a per-test queue and delete it afterwards."""
    import aio_pika

    name = f"doccontext_test_{uuid.uuid4().hex[:10]}"
    yield name
    conn = await aio_pika.connect_robust(settings.rabbitmq_url)
    try:
        channel = await conn.channel()
        await channel.queue_delete(name)
    finally:
        await conn.close()


async def _collect(
    consumer: RabbitMQConsumer,
    queue: str,
    *,
    expected: int,
    timeout: float = 5.0,
    handler_side_effect=None,
) -> list[dict[str, Any]]:
    """Run consume() as a task, collect `expected` messages, cancel, return them."""
    received: list[dict[str, Any]] = []
    done = asyncio.Event()

    async def handler(payload: Mapping[str, Any]) -> None:
        received.append(dict(payload))
        if len(received) >= expected:
            done.set()
        if handler_side_effect is not None:
            handler_side_effect(dict(payload))

    task = asyncio.create_task(consumer.consume(queue=queue, handler=handler))
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return received


async def test_publish_then_consume_roundtrip(
    settings: Settings, queue_name: str
) -> None:
    publisher = RabbitMQPublisher(settings)
    consumer = RabbitMQConsumer(settings)
    payload = {
        "job_id": str(uuid.uuid4()),
        "job_type": "INDEX_DOCUMENT",
        "document_id": "doc-1",
    }

    try:
        await publisher.publish(queue=queue_name, payload=payload)
        received = await _collect(consumer, queue_name, expected=1)
        assert received == [payload]
    finally:
        await publisher.close()
        await consumer.close()


async def test_consumer_processes_messages_in_publish_order(
    settings: Settings, queue_name: str
) -> None:
    publisher = RabbitMQPublisher(settings)
    consumer = RabbitMQConsumer(settings)
    payloads = [{"seq": i} for i in range(5)]

    try:
        for p in payloads:
            await publisher.publish(queue=queue_name, payload=p)
        received = await _collect(consumer, queue_name, expected=len(payloads))
        assert received == payloads
    finally:
        await publisher.close()
        await consumer.close()


async def test_consumer_drops_poison_messages_and_continues(
    settings: Settings, queue_name: str
) -> None:
    """A handler that raises should nack-without-requeue; later messages still flow."""
    publisher = RabbitMQPublisher(settings)
    consumer = RabbitMQConsumer(settings)

    try:
        await publisher.publish(queue=queue_name, payload={"seq": "poison"})
        await publisher.publish(queue=queue_name, payload={"seq": "good"})

        def blow_up_on_poison(payload: dict[str, Any]) -> None:
            if payload.get("seq") == "poison":
                raise RuntimeError("boom")

        received = await _collect(
            consumer,
            queue_name,
            expected=2,
            handler_side_effect=blow_up_on_poison,
        )
        assert [m["seq"] for m in received] == ["poison", "good"]
    finally:
        await publisher.close()
        await consumer.close()


async def test_publisher_close_is_idempotent(settings: Settings) -> None:
    publisher = RabbitMQPublisher(settings)
    q = f"doccontext_test_close_{uuid.uuid4().hex[:6]}"
    try:
        await publisher.publish(queue=q, payload={"x": 1})
        await publisher.close()
        # Second close must not raise.
        await publisher.close()
    finally:
        import aio_pika

        conn = await aio_pika.connect_robust(settings.rabbitmq_url)
        try:
            channel = await conn.channel()
            await channel.queue_delete(q)
        finally:
            await conn.close()
