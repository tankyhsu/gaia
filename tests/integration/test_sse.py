from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from examples.controlled_task.app import create_app
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


def test_sse_endpoint_resumes_after_last_event_id_and_closes_for_terminal_run(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/sse.db"
    headers = {"X-Gaia-Api-Key": "gaia-dev-key"}
    with TestClient(create_app(database_url)) as client:
        created = client.post(
            "/v1/runs",
            headers={**headers, "Idempotency-Key": "sse-read-123"},
            json={
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": {"id": "u", "organization": "org-alpha", "roles": ["reader"]},
                "request": {"text": "inspect res-001"},
            },
        )
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        events = client.get(f"/v1/runs/{run_id}/events", headers=headers).json()
        resume_after = events[-2]["sequence"]

        response = client.get(
            f"/v1/runs/{run_id}/events/stream",
            headers={**headers, "Last-Event-ID": str(resume_after)},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text.count("event: run.event\n") == 1
    assert f"id: {events[-1]['sequence']}\n" in response.text
    assert json.loads(response.text.split("data: ", 1)[1])["event_id"] == events[-1]["event_id"]


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
