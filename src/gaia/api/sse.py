"""Server-sent event delivery for durable Run events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

from gaia.contracts.models import RunEvent, RunSnapshot, RunStatus


class EventRuntime(Protocol):
    async def inspect(self, run_id: str) -> RunSnapshot: ...

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]: ...


class DisconnectAwareRequest(Protocol):
    async def is_disconnected(self) -> bool: ...


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.DEGRADED,
        RunStatus.BLOCKED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


async def stream_run_events(
    request: DisconnectAwareRequest,
    runtime: EventRuntime,
    run_id: str,
    *,
    last_event_id: int,
    poll_interval_seconds: float,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    """Yield resumable SSE frames until the Run reaches a terminal state."""
    if poll_interval_seconds <= 0 or heartbeat_seconds <= 0:
        raise ValueError("SSE intervals must be positive")

    cursor = last_event_id
    loop = asyncio.get_running_loop()
    last_emit_at = loop.time()

    while True:
        if await request.is_disconnected():
            return

        events = await runtime.events_after(run_id, cursor)
        for event in events:
            if await request.is_disconnected():
                return
            cursor = event.sequence
            last_emit_at = loop.time()
            yield _event_frame(event)

        snapshot = await runtime.inspect(run_id)
        if snapshot.status in TERMINAL_STATUSES:
            # Status and its final event commit together, but they may become visible
            # between the preceding event query and this snapshot query.
            trailing_events = await runtime.events_after(run_id, cursor)
            for event in trailing_events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                yield _event_frame(event)
            return

        now = loop.time()
        until_heartbeat = heartbeat_seconds - (now - last_emit_at)
        if until_heartbeat <= 0:
            last_emit_at = now
            yield ": heartbeat\n\n"
            continue

        await asyncio.sleep(min(poll_interval_seconds, until_heartbeat))


def _event_frame(event: RunEvent) -> str:
    payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.sequence}\nevent: run.event\ndata: {payload}\n\n"
