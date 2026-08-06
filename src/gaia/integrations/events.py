"""Concrete event publisher integrations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from gaia.spi.events import EventEnvelope

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class InProcessEventPublisher:
    """Process-local publisher used until a durable MQ adapter is selected."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        if not topic:
            raise ValueError("topic must not be empty")
        self._handlers.setdefault(topic, []).append(handler)

    async def publish(self, event: EventEnvelope) -> None:
        handlers = [*self._handlers.get(event.topic, ()), *self._handlers.get("*", ())]
        for handler in handlers:
            await handler(event)
