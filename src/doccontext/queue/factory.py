from __future__ import annotations

from doccontext.config import Settings, get_settings
from doccontext.queue.base import QueueConsumer, QueuePublisher


class UnknownQueueProvider(ValueError):
    pass


_KNOWN_PROVIDERS = {"rabbitmq", "sqs", "nats", "kafka", "redis"}


def get_queue_publisher(settings: Settings | None = None) -> QueuePublisher:
    s = settings or get_settings()
    provider = s.queue_provider
    if provider == "rabbitmq":
        from doccontext.queue.rabbitmq import RabbitMQPublisher

        return RabbitMQPublisher(s)
    if provider in _KNOWN_PROVIDERS:
        raise NotImplementedError(
            f"queue provider {provider!r} is reserved but not yet implemented"
        )
    raise UnknownQueueProvider(f"unknown queue provider: {provider!r}")


def get_queue_consumer(settings: Settings | None = None) -> QueueConsumer:
    s = settings or get_settings()
    provider = s.queue_provider
    if provider == "rabbitmq":
        from doccontext.queue.rabbitmq import RabbitMQConsumer

        return RabbitMQConsumer(s)
    if provider in _KNOWN_PROVIDERS:
        raise NotImplementedError(
            f"queue provider {provider!r} is reserved but not yet implemented"
        )
    raise UnknownQueueProvider(f"unknown queue provider: {provider!r}")
