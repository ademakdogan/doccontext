from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

import aio_pika

from doccontext.config import Settings, get_settings
from doccontext.queue.base import MessageHandler, QueueConsumer, QueuePublisher

_logger = logging.getLogger(__name__)


class _RabbitMQClient:
    """Shared connection/channel bookkeeping for the RabbitMQ pub/sub pair."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None

    async def _channel_open(self) -> aio_pika.abc.AbstractChannel:
        if self._connection is None or self._connection.is_closed:
            self._connection = await aio_pika.connect_robust(
                self._settings.rabbitmq_url
            )
        if self._channel is None or self._channel.is_closed:
            self._channel = await self._connection.channel()
        return self._channel

    async def close(self) -> None:
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
        self._channel = None
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None


class RabbitMQPublisher(_RabbitMQClient, QueuePublisher):
    async def publish(self, *, queue: str, payload: Mapping[str, Any]) -> None:
        channel = await self._channel_open()
        await channel.declare_queue(queue, durable=True)
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=queue,
        )


class RabbitMQConsumer(_RabbitMQClient, QueueConsumer):
    async def consume(
        self,
        *,
        queue: str,
        handler: MessageHandler,
        prefetch: int = 1,
    ) -> None:
        channel = await self._channel_open()
        await channel.set_qos(prefetch_count=prefetch)
        q = await channel.declare_queue(queue, durable=True)
        async with q.iterator() as it:
            async for message in it:
                # process() acks on normal exit, nacks on exception. Poison
                # messages are dropped (requeue=False) so a failing job cannot
                # spin the worker forever; the job repo records FAILED.
                # Handler exceptions are swallowed here so the consumer loop
                # survives a single bad message.
                try:
                    async with message.process(requeue=False):
                        payload = json.loads(message.body.decode("utf-8"))
                        await handler(payload)
                except Exception:
                    _logger.exception(
                        "queue handler raised; message dropped",
                        extra={"queue": queue},
                    )
