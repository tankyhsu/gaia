from __future__ import annotations

import pytest

from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import (
    Decision,
    ExecutionPolicy,
    HumanGateDecisionRequest,
    RunMode,
    RunRequest,
    UserIdentity,
    VersionBundle,
)
from gaia.runtime.contracts import RuntimePermissionDenied, RuntimeRunNotFound
from gaia.runtime.dependencies import RuntimeDependencies, ToolRegistry
from gaia.runtime.temporal_runtime import (
    TemporalRuntimeEngine,
    TemporalRuntimeUnavailable,
)


class AdmissionRunner:
    @property
    def version_bundle(self) -> VersionBundle:
        return VersionBundle(
            policy="policy:1",
            workflow="workflow:1",
            rules="rules:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        )

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return ExecutionPolicy(
            policy_id="policy",
            version="1",
            scenario_id="ticket.prepare",
            allowed_tools=[],
            recognized_roles=["employee"],
            max_steps=10,
            max_duration_seconds=30,
            max_model_calls=1,
            write_mode="disabled",
            human_gate_rules=[],
        )


def _request() -> RunRequest:
    return RunRequest(
        scenario_id="ticket.prepare",
        mode=RunMode.MOCK,
        user=UserIdentity(id="employee-1", organization="gaia", roles=["employee"]),
        request={"text": "Create an IT ticket"},
    )


def test_temporal_plan_is_deterministic() -> None:
    settings = RuntimeExecutionSettings(
        provider="temporal",
        namespace="runtime-ns",
        task_queue="runtime-q",
        server_address="temporal.local:9123",
        task_timeout_seconds=31,
        max_concurrent_workflows=128,
    )
    runtime = TemporalRuntimeEngine(execution=settings)
    plan = runtime.plan

    assert plan.namespace == "runtime-ns"
    assert plan.task_queue == "runtime-q"
    assert plan.server_address == "temporal.local:9123"
    assert plan.server_host == "temporal.local"
    assert plan.server_port == 9123
    assert plan.tls_enabled is False
    assert plan.task_timeout_seconds == 31
    assert plan.max_concurrent_workflows == 128


def test_temporal_create_envelope_carries_migration_inputs() -> None:
    request = _request()
    runtime = TemporalRuntimeEngine()
    envelope = runtime.build_create_envelope(request, "idem-001")

    assert envelope.operation == "create"
    assert envelope.payload["idempotency_key"] == "idem-001"
    assert envelope.payload["request"]["scenario_id"] == request.scenario_id
    assert isinstance(envelope.payload["request_fingerprint"], str)
    assert envelope.payload["issued_at"] == envelope.issued_at


def test_temporal_decision_envelope_carries_complete_audit_evidence() -> None:
    envelope = TemporalRuntimeEngine().build_decide_envelope(
        "gate-1",
        HumanGateDecisionRequest(
            decision=Decision.APPROVED,
            decided_by="approver-1",
            roles=["approver"],
            comment="Approved after checking the request.",
        ),
    )

    assert envelope.payload == {
        "gate_id": "gate-1",
        "decision": "approved",
        "decided_by": "approver-1",
        "roles": ("approver",),
        "comment": "Approved after checking the request.",
    }


@pytest.mark.asyncio
async def test_temporal_not_ready_error_includes_plan_and_envelope() -> None:
    runtime = TemporalRuntimeEngine(
        execution=RuntimeExecutionSettings(provider="temporal", task_queue="q-main")
    )
    with pytest.raises(TemporalRuntimeUnavailable) as error:
        await runtime.inspect("run-001")
    message = str(error.value)
    assert "runtime.operation=inspect" in message
    assert "migration.envelope" in message
    assert "temporal.namespace='default'" in message
    assert "temporal.task_queue='q-main'" in message
    assert "temporal.server='127.0.0.1:7233'" in message
    assert "temporal.tls_enabled=False" in message


@pytest.mark.asyncio
async def test_temporal_rejects_request_mode_before_workflow_start() -> None:
    backend_called = False

    async def backend(operation: str, payload: dict[str, object]) -> object:
        nonlocal backend_called
        del operation, payload
        backend_called = True
        return {}

    runtime = TemporalRuntimeEngine(
        backend=backend,
        dependencies=RuntimeDependencies(
            runners={"ticket.prepare": AdmissionRunner()},
            write_tools=ToolRegistry(),
            environment=RunMode.SANDBOX,
        ),
    )

    with pytest.raises(RuntimePermissionDenied, match="ENVIRONMENT_MODE_MISMATCH"):
        await runtime.create(_request(), "sandbox-mode-mismatch")

    assert backend_called is False


class RecordingProjection:
    """The archive side of a read: it knows the Run, Temporal no longer does."""

    def __init__(self, run: dict[str, object] | None = None) -> None:
        self._run = run
        self.list_calls: list[dict[str, object]] = []
        self.gates_for_run_calls: list[str] = []
        self.gates: list[dict[str, object]] = []

    async def record(self, **_: object) -> None:  # pragma: no cover - unused here
        raise AssertionError("reads must not write evidence")

    async def get_run(self, run_id: str) -> dict[str, object] | None:
        return self._run

    async def list_runs(self, **kwargs: object) -> dict[str, object]:
        self.list_calls.append(kwargs)
        return {"items": [], "next_cursor": None}

    async def events_after(self, run_id: str, sequence: int = 0) -> list[dict[str, object]]:
        return []

    async def get_gate(self, gate_id: str) -> dict[str, object] | None:
        return None

    async def gates_for_run(self, run_id: str) -> list[dict[str, object]]:
        self.gates_for_run_calls.append(run_id)
        return self.gates


def _archived_snapshot(run_id: str = "run-1") -> dict[str, object]:
    return {
        "run_id": run_id,
        "scenario_id": "ticket.prepare",
        "mode": "mock",
        "status": "succeeded",
        "user": {"id": "alice", "organization": "gaia", "roles": ["employee"]},
        "version_bundle": {
            "policy": "policy:1",
            "workflow": "workflow:1",
            "rules": "rules:1",
            "prompt": "prompt:1",
            "model_profile": "model:1",
            "toolset": "tools:1",
            "context_profile": "context:1",
        },
        "result": {"ok": True},
        "created_at": "2026-07-29T00:00:00+00:00",
        "updated_at": "2026-07-29T00:00:01+00:00",
    }


@pytest.mark.asyncio
async def test_a_run_temporal_has_deleted_is_still_readable() -> None:
    """Past the retention window, evidence answers instead of Temporal."""

    async def backend(operation: str, payload: dict[str, object]) -> object:
        raise RuntimeRunNotFound("run-1")

    runtime = TemporalRuntimeEngine(
        backend=backend,
        audit_projection=RecordingProjection(_archived_snapshot()),
    )

    snapshot = await runtime.inspect("run-1")

    assert snapshot.status.value == "succeeded"
    assert snapshot.result == {"ok": True}


@pytest.mark.asyncio
async def test_a_run_nobody_has_a_record_of_reads_as_not_found() -> None:
    """`KeyError`, not an infrastructure error: the API must answer 404, not 500."""

    async def backend(operation: str, payload: dict[str, object]) -> object:
        raise RuntimeRunNotFound("run-missing")

    runtime = TemporalRuntimeEngine(
        backend=backend,
        audit_projection=RecordingProjection(None),
    )

    with pytest.raises(KeyError):
        await runtime.inspect("run-missing")


@pytest.mark.asyncio
async def test_listing_never_reaches_the_execution_provider() -> None:
    """Listing is an evidence query. Routing it through Temporal is the bug being fixed."""

    async def backend(operation: str, payload: dict[str, object]) -> object:
        raise AssertionError(f"listing must not dispatch {operation!r} to Temporal")

    projection = RecordingProjection()
    runtime = TemporalRuntimeEngine(backend=backend, audit_projection=projection)

    page = await runtime.list_runs(organization="gaia", limit=25)

    assert page.items == []
    assert projection.list_calls == [
        {
            "organization": "gaia",
            "status": None,
            "scenario_id": None,
            "limit": 25,
            "cursor": None,
        }
    ]


@pytest.mark.asyncio
async def test_gates_for_run_never_reaches_the_execution_provider() -> None:
    """Like listing, this is an evidence query -- Temporal Workflow History
    only ever exposes the current gate, never the full set a Run opened."""

    async def backend(operation: str, payload: dict[str, object]) -> object:
        raise AssertionError(f"gates_for_run must not dispatch {operation!r} to Temporal")

    projection = RecordingProjection()
    projection.gates = [
        {
            "gate_id": "run-1:gate:publish",
            "run_id": "run-1",
            "command_id": "run-1:command:publish",
            "reason": "Publishing changes a durable business record.",
            "risk_level": "high",
            "requested_action": {"resource_id": "widget-1"},
            "approval_view": None,
            "status": "approved",
            "requested_by": "alice",
            "decided_by": "demo-approver",
            "comment": None,
            "created_at": "2026-07-29T00:00:00+00:00",
            "expires_at": "2026-07-30T00:00:00+00:00",
            "decided_at": "2026-07-29T00:00:05+00:00",
        }
    ]
    runtime = TemporalRuntimeEngine(backend=backend, audit_projection=projection)

    gates = await runtime.gates_for_run("run-1")

    assert [gate.decided_by for gate in gates] == ["demo-approver"]
    assert projection.gates_for_run_calls == ["run-1"]


@pytest.mark.asyncio
async def test_gates_for_run_without_a_projection_is_reported_as_unavailable() -> None:
    async def backend(operation: str, payload: dict[str, object]) -> object:
        raise AssertionError(f"gates_for_run must not dispatch {operation!r} to Temporal")

    runtime = TemporalRuntimeEngine(backend=backend)

    with pytest.raises(TemporalRuntimeUnavailable):
        await runtime.gates_for_run("run-1")
