from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

MessageHandler = Callable[[Mapping[str, Any]], Awaitable[None]]


class QueuePublisher(abc.ABC):
    """Publishes JSON-serialisable envelopes onto a named queue."""

    @abc.abstractmethod
    async def publish(self, *, queue: str, payload: Mapping[str, Any]) -> None:
        """Enqueue ``payload`` onto ``queue``. Declares the queue if absent."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/channel. Idempotent."""


class QueueConsumer(abc.ABC):
    """Long-running consumer that dispatches messages to a handler."""

    @abc.abstractmethod
    async def consume(
        self,
        *,
        queue: str,
        handler: MessageHandler,
        prefetch: int = 1,
    ) -> None:
        """Block forever, invoking ``handler`` once per message.

        The message is acked on handler success, nacked (without requeue) on
        exception. Callers propagate ``asyncio.CancelledError`` to stop.
        """

    @abc.abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/channel. Idempotent."""
