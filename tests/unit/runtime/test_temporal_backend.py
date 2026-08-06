from __future__ import annotations

from typing import Any

import pytest

from gaia.config.models import RuntimeExecutionSettings
from gaia.runtime.temporal_backend import TemporalClientBackend
from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_RUNTIME_WORKFLOW,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeUnavailable


class FakeHandle:
    def __init__(self, snapshot: dict[str, object], fingerprint: str) -> None:
        self.snapshot = snapshot
        self.fingerprint = fingerprint
        self.signals: list[tuple[str, object]] = []

    async def query(self, query: str, arg: Any = None) -> object:
        if query == "snapshot":
            return self.snapshot
        if query == "request_fingerprint":
            return self.fingerprint
        if query == "events_after":
            return [{"sequence": 1, "arg": arg}]
        if query == "gate":
            return {"gate_id": arg, "status": "pending"}
        raise AssertionError(query)

    async def signal(self, signal: str, arg: Any = None) -> None:
        self.signals.append((signal, arg))

    async def execute_update(self, update: str, arg: Any = None) -> object:
        self.signals.append((update, arg))
        return self.snapshot


class FakeClient:
    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle
        self.started: tuple[str, dict[str, object], dict[str, object]] | None = None
        self.requested_ids: list[str] = []

    async def start_workflow(
        self,
        workflow: str,
        arg: dict[str, object],
        **kwargs: object,
    ) -> FakeHandle:
        self.started = (workflow, arg, kwargs)
        return self.handle

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        self.requested_ids.append(workflow_id)
        return self.handle


def _create_payload() -> dict[str, object]:
    return {
        "request": {
            "scenario_id": "ticket.prepare",
            "mode": "mock",
            "user": {
                "id": "employee-1",
                "organization": "gaia",
                "roles": ["employee"],
            },
            "request": {"text": "Create an IT ticket", "metadata": {}},
        },
        "idempotency_key": "idem-001",
        "request_fingerprint": "fingerprint-1",
        "issued_at": "2026-07-29T00:00:00+00:00",
        "human_gate_ttl_seconds": 86400,
        "version_bundle": {
            "policy": "policy:1",
            "workflow": "workflow:1",
            "rules": "rules:1",
            "prompt": "prompt:1",
            "model_profile": "model:1",
            "toolset": "tools:1",
            "context_profile": "context:1",
        },
    }


async def _client(client: FakeClient) -> FakeClient:
    return client


@pytest.mark.asyncio
async def test_create_starts_real_workflow_contract_and_returns_snapshot() -> None:
    snapshot = {"run_id": "gaia-run-existing", "status": "received"}
    handle = FakeHandle(snapshot, "fingerprint-1")
    client = FakeClient(handle)
    backend = TemporalClientBackend(
        RuntimeExecutionSettings(task_queue="runtime-q"),
        client_factory=lambda: _client(client),
    )

    result = await backend("create", _create_payload())

    assert result == snapshot
    assert client.started is not None
    workflow, workflow_input, options = client.started
    assert workflow == GAIA_RUNTIME_WORKFLOW
    assert workflow_input["run_id"].startswith("gaia-run-")
    assert workflow_input["activity_timeout_seconds"] == 30
    assert options["task_queue"] == "runtime-q"
    attributes = options["search_attributes"]
    assert attributes.get(GAIA_ORGANIZATION_SEARCH_ATTRIBUTE) == "gaia"
    assert attributes.get(GAIA_SCENARIO_SEARCH_ATTRIBUTE) == "ticket.prepare"
    assert attributes.get(GAIA_STATUS_SEARCH_ATTRIBUTE) == "received"


@pytest.mark.asyncio
async def test_inspect_and_cancel_target_run_workflow() -> None:
    snapshot = {"run_id": "run-1", "status": "received"}
    handle = FakeHandle(snapshot, "fingerprint-1")
    client = FakeClient(handle)
    backend = TemporalClientBackend(
        RuntimeExecutionSettings(provider="temporal"),
        client_factory=lambda: _client(client),
    )

    assert await backend("inspect", {"run_id": "run-1"}) == snapshot
    assert await backend("cancel", {"run_id": "run-1", "reason": "operator"}) == snapshot
    assert client.requested_ids == ["run-1", "run-1"]
    assert handle.signals == [("cancel", {"run_id": "run-1", "reason": "operator"})]


@pytest.mark.asyncio
async def test_gate_query_and_decision_update_route_to_owning_workflow() -> None:
    snapshot = {"run_id": "run-1", "status": "waiting_human"}
    handle = FakeHandle(snapshot, "fingerprint-1")
    client = FakeClient(handle)
    backend = TemporalClientBackend(
        RuntimeExecutionSettings(provider="temporal"),
        client_factory=lambda: _client(client),
    )
    gate_id = "run-1:gate:write-1"
    decision = {
        "gate_id": gate_id,
        "decision": "approved",
        "decided_by": "approver-1",
        "roles": ("approver",),
        "comment": "approved",
    }

    await backend("get_gate", {"gate_id": gate_id})
    assert await backend("decide", decision) == snapshot

    assert client.requested_ids == ["run-1", "run-1"]
    assert handle.signals == [("decide", decision)]


@pytest.mark.asyncio
async def test_backend_refuses_to_list_runs_from_temporal() -> None:
    """Listing belongs to Gaia's audit projection, not to Temporal Visibility.

    Visibility listing needed one Workflow Query per row to recover a snapshot,
    was unavailable whenever the Workers were down, and returned nothing at all
    for Runs past the namespace retention window. Leaving a second, weaker
    listing path wired up is how callers end up back on it.
    """

    backend = TemporalClientBackend(
        RuntimeExecutionSettings(provider="temporal"),
        client_factory=lambda: _client(FakeClient(FakeHandle({}, "fingerprint-1"))),
    )

    with pytest.raises(TemporalRuntimeUnavailable):
        await backend("list_runs", {"organization": "gaia", "limit": 10})
