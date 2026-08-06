"""`InMemoryAuditProjection` must not be weaker than the real store it doubles for.

`gates_for_run` is the read the demo landing page and the Run list use to
answer "who approved this Run" -- if this double's ordering or filtering
diverged from `SqlAlchemyAuditProjection`'s, a test written against the double
could pass while the same behaviour broke in production. See
`tests/unit/persistence/test_audit_projection.py` for the equivalent
assertions against the real store; this file exists so both are held to the
same bar.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gaia.testing import InMemoryAuditProjection


def _snapshot(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "scenario_id": "controlled-task",
        "mode": "mock",
        "status": "succeeded",
        "user": {"id": "alice", "organization": "gaia", "roles": ["operator"]},
        "version_bundle": {"policy": "p:1.0.0"},
        "created_at": "2026-07-29T00:00:00+00:00",
        "updated_at": "2026-07-29T00:00:00+00:00",
    }


def _gate(
    run_id: str,
    gate_id: str,
    *,
    status: str = "pending",
    decided_by: str | None = None,
    created_at: str = "2026-07-29T00:00:00+00:00",
) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "run_id": run_id,
        "command_id": f"{gate_id}:command",
        "reason": "Publishing changes a durable business record.",
        "risk_level": "high",
        "requested_action": {"resource_id": "widget-1"},
        "approval_view": None,
        "status": status,
        "requested_by": "alice",
        "decided_by": decided_by,
        "comment": None,
        "created_at": created_at,
        "expires_at": "2026-07-30T00:00:00+00:00",
        "decided_at": None,
    }


async def test_gates_for_run_returns_every_gate_the_run_opened_oldest_first() -> None:
    projection = InMemoryAuditProjection()
    first = _gate("run-1", "run-1:gate:first", created_at="2026-07-29T00:00:00+00:00")
    second = _gate("run-1", "run-1:gate:second", created_at="2026-07-29T00:05:00+00:00")

    await projection.record(snapshot=_snapshot("run-1"), events=[], gates=[second, first])
    # Approval only ever lands through `record_decision` -- the authenticated
    # API path -- never through `record`'s projection from the Workflow. See
    # `test_gates_for_run_never_reports_a_forged_temporal_approval` below.
    await projection.record_decision(
        gate=second,
        decision="approved",
        decided_by="demo-approver",
        comment=None,
        decided_at=datetime.now(UTC),
    )

    gates = await projection.gates_for_run("run-1")

    assert [gate["gate_id"] for gate in gates] == [
        "run-1:gate:first",
        "run-1:gate:second",
    ]
    assert gates[1]["decided_by"] == "demo-approver"


async def test_gates_for_run_never_returns_another_runs_gate() -> None:
    projection = InMemoryAuditProjection()
    await projection.record(
        snapshot=_snapshot("run-1"),
        events=[],
        gates=[_gate("run-1", "run-1:gate:publish")],
    )
    await projection.record(
        snapshot=_snapshot("run-2"),
        events=[],
        gates=[_gate("run-2", "run-2:gate:publish")],
    )

    gates = await projection.gates_for_run("run-1")

    assert [gate["gate_id"] for gate in gates] == ["run-1:gate:publish"]


async def test_gates_for_run_is_empty_when_the_run_never_opened_one() -> None:
    projection = InMemoryAuditProjection()
    await projection.record(snapshot=_snapshot("run-1"), events=[], gates=[])

    assert await projection.gates_for_run("run-1") == []


async def test_gates_for_run_never_reports_a_forged_temporal_approval() -> None:
    """The Workflow cannot grant approval (see `_project_gate`); a gate this
    double received as "approved" straight from `record` must still read
    back as `pending` through `gates_for_run`, exactly as it does through
    `get_gate` -- otherwise this read path would reopen the forged-approval
    hole `record_decision` exists to close."""

    projection = InMemoryAuditProjection()
    forged = _gate("run-1", "run-1:gate:publish", status="approved", decided_by="mallory")

    await projection.record(snapshot=_snapshot("run-1"), events=[], gates=[forged])

    gates = await projection.gates_for_run("run-1")

    assert gates[0]["status"] == "pending"
    assert gates[0]["decided_by"] is None
