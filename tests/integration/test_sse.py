from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from gaia.api.sse import stream_run_events
from gaia.contracts.models import ActorType, EventStatus, RunEvent, RunStatus


class FakeRequest:
    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


class FakeRuntime:
    def __init__(self, status: RunStatus, events: list[RunEvent] | None = None) -> None:
        self.status = status
        self.events = events or []
        self.event_queries = 0

    async def inspect(self, run_id: str) -> Any:
        return SimpleNamespace(status=self.status)

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]:
        self.event_queries += 1
        return [event for event in self.events if event.sequence > sequence]


async def test_sse_waits_with_heartbeat_then_delivers_terminal_event() -> None:
    request = FakeRequest()
    runtime = FakeRuntime(RunStatus.WAITING_HUMAN)
    stream = stream_run_events(
        request,
        runtime,
        "run-1",
        last_event_id=0,
        poll_interval_seconds=0.001,
        heartbeat_seconds=0.01,
    )

    assert await asyncio.wait_for(anext(stream), timeout=0.2) == ": heartbeat\n\n"

    event = _event(1)
    runtime.events.append(event)
    runtime.status = RunStatus.SUCCEEDED
    frame = await asyncio.wait_for(anext(stream), timeout=0.2)
    assert "event: run.event\n" in frame
    assert f"id: {event.sequence}\n" in frame
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_sse_stops_immediately_after_client_disconnect() -> None:
    request = FakeRequest()
    request.disconnected = True
    runtime = FakeRuntime(RunStatus.WAITING_HUMAN)
    stream = stream_run_events(
        request,
        runtime,
        "run-1",
        last_event_id=0,
        poll_interval_seconds=0.001,
        heartbeat_seconds=0.01,
    )

    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert runtime.event_queries == 0


async def test_sse_fetches_final_event_committed_between_query_and_terminal_snapshot() -> None:
    event = _event(1)

    class CommitRaceRuntime(FakeRuntime):
        async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]:
            self.event_queries += 1
            return [] if self.event_queries == 1 else [event]

    request = FakeRequest()
    runtime = CommitRaceRuntime(RunStatus.SUCCEEDED)
    stream = stream_run_events(
        request,
        runtime,
        "run-1",
        last_event_id=0,
        poll_interval_seconds=0.001,
        heartbeat_seconds=0.01,
    )

    assert f"id: {event.sequence}\n" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


def _event(sequence: int) -> RunEvent:
    return RunEvent(
        event_id=f"evt-{sequence}",
        run_id="run-1",
        sequence=sequence,
        timestamp=datetime.now(UTC),
        actor=ActorType.SYSTEM,
        step="finalize",
        status=EventStatus.SUCCEEDED,
        source_refs=[],
        rule_refs=[],
    )
