"""The durable audit projection: what still answers after Temporal forgets.

These tests exercise the real SQLAlchemy store against SQLite rather than a
fake, because the properties under test -- replay safety, keyset paging,
organization scoping -- are properties of the queries, not of the interface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.runtime.contracts import InvalidRunCursor


def _snapshot(
    run_id: str,
    *,
    organization: str = "gaia",
    scenario_id: str = "ticket.prepare",
    status: str = "running",
    created_at: str = "2026-07-29T00:00:00+00:00",
    updated_at: str | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "mode": "mock",
        "status": status,
        "user": {"id": "alice", "organization": organization, "roles": ["user"]},
        "version_bundle": {"policy": "p:1.0.0"},
        "created_at": created_at,
        "updated_at": updated_at or created_at,
    }


def _event(run_id: str, sequence: int, step: str = "start_workflow") -> dict[str, object]:
    return {
        "event_id": f"{run_id}:{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "timestamp": "2026-07-29T00:00:00+00:00",
        "actor": "system",
        "step": step,
        "status": "succeeded",
        "source_refs": [],
        "rule_refs": [],
        "details": {},
    }


def _gate(
    run_id: str,
    *,
    status: str = "pending",
    decided_by: str | None = None,
    created_at: str = "2026-07-29T00:00:00+00:00",
) -> dict[str, object]:
    return {
        "gate_id": f"{run_id}:gate:publish",
        "run_id": run_id,
        "command_id": f"{run_id}:command:publish",
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


@pytest.fixture
async def projection(tmp_path: Path):
    # A file-backed database, not `:memory:`: the projection opens a session per
    # call, and the point of this store is that the data survives the connection.
    url = f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}"
    factory = await initialize_database(url)
    try:
        yield SqlAlchemyAuditProjection(factory)
    finally:
        await dispose_session_factory(factory)


@pytest.mark.asyncio
async def test_replaying_the_same_projection_does_not_duplicate_evidence(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """Temporal is entitled to retry `record_audit`; evidence must not multiply."""

    snapshot = _snapshot("run-1")
    events = [_event("run-1", 1), _event("run-1", 2)]

    await projection.record(snapshot=snapshot, events=events, gates=[])
    await projection.record(snapshot=snapshot, events=events, gates=[])

    recorded = await projection.events_after("run-1", 0)
    assert [item["sequence"] for item in recorded] == [1, 2]


@pytest.mark.asyncio
async def test_a_late_projection_cannot_move_a_run_backwards(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """An out-of-order retry must not resurrect a superseded status.

    A Run that has already been recorded as `succeeded` is not allowed to read
    back as `running` because an older Activity attempt landed afterwards.
    """

    await projection.record(
        snapshot=_snapshot("run-1", status="running", updated_at="2026-07-29T00:00:01+00:00"),
        events=[_event("run-1", 1)],
        gates=[],
    )
    await projection.record(
        snapshot=_snapshot("run-1", status="succeeded", updated_at="2026-07-29T00:00:09+00:00"),
        events=[_event("run-1", 2, step="finalize")],
        gates=[],
    )
    await projection.record(
        snapshot=_snapshot("run-1", status="running", updated_at="2026-07-29T00:00:05+00:00"),
        events=[],
        gates=[],
    )

    stored = await projection.get_run("run-1")
    assert stored is not None
    assert stored["status"] == "succeeded"


@pytest.mark.asyncio
async def test_a_decided_gate_is_never_overwritten_by_a_pending_replay(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """Who approved a write is the single most re-checkable fact in the store."""

    snapshot = _snapshot("run-1", status="waiting_human")
    await projection.record(snapshot=snapshot, events=[], gates=[_gate("run-1")])
    assert await projection.record_decision(
        gate=_gate("run-1"),
        decision="approved",
        decided_by="carol",
        comment="Approved.",
        decided_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    await projection.record(snapshot=snapshot, events=[], gates=[_gate("run-1")])

    stored = await projection.get_gate("run-1:gate:publish")
    assert stored is not None
    assert stored["status"] == "approved"
    assert stored["decided_by"] == "carol"


@pytest.mark.asyncio
async def test_the_workflow_cannot_project_an_approval_it_was_told_about(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """The Workflow is not a trusted source of authorization.

    Anyone who can reach the Temporal namespace can send the `decide` Update
    with `roles=["approver"]`, and the Workflow believes it. If that forged
    decision could flow into this store, it would become the very record
    `execute_command` consults before performing the write.

    Withholding authority is still allowed from that path -- a rejection or an
    expiry only ever denies.
    """

    snapshot = _snapshot("run-1", status="waiting_human")
    await projection.record(snapshot=snapshot, events=[], gates=[_gate("run-1")])
    await projection.record(
        snapshot=snapshot,
        events=[],
        gates=[_gate("run-1", status="approved", decided_by="attacker")],
    )

    stored = await projection.get_gate("run-1:gate:publish")
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored.get("decided_by") is None

    await projection.record(
        snapshot=snapshot,
        events=[],
        gates=[_gate("run-1", status="rejected", decided_by="dave")],
    )
    denied = await projection.get_gate("run-1:gate:publish")
    assert denied is not None
    assert denied["status"] == "rejected"


@pytest.mark.asyncio
async def test_a_first_projection_that_claims_approval_is_downgraded(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """A forged approval must not slip in as the gate's very first record."""

    await projection.record(
        snapshot=_snapshot("run-1", status="waiting_human"),
        events=[],
        gates=[_gate("run-1", status="approved", decided_by="attacker")],
    )

    stored = await projection.get_gate("run-1:gate:publish")
    assert stored is not None
    assert stored["status"] == "pending"


@pytest.mark.asyncio
async def test_recording_the_same_decision_twice_is_not_a_conflict(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """The decision is written before Temporal hears about it, so retries happen.

    Treating the retry as a conflict would strand the Run on a gate Gaia already
    considers decided.
    """

    await projection.record(
        snapshot=_snapshot("run-1", status="waiting_human"),
        events=[],
        gates=[_gate("run-1")],
    )
    decision = {
        "gate": _gate("run-1"),
        "decision": "approved",
        "decided_by": "carol",
        "comment": "Approved.",
        "decided_at": datetime(2026, 7, 30, tzinfo=UTC),
    }

    assert await projection.record_decision(**decision)
    assert await projection.record_decision(**decision)
    assert not await projection.record_decision(**{**decision, "decided_by": "mallory"})
    assert not await projection.record_decision(**{**decision, "decision": "rejected"})

    stored = await projection.get_gate("run-1:gate:publish")
    assert stored is not None
    assert stored["decided_by"] == "carol"


@pytest.mark.asyncio
async def test_a_decision_can_land_before_the_workflow_projects_the_gate(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """The projection trails the Workflow by one Activity round-trip.

    An approver who acts inside that window is approving a gate that genuinely
    exists -- the API read it from Temporal to authorize them. Refusing would be
    a race, not a control, so the authenticated path inserts it as decided.
    """

    recorded = await projection.record_decision(
        gate=_gate("run-9"),
        decision="approved",
        decided_by="carol",
        comment="Approved.",
        decided_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert recorded
    stored = await projection.get_gate("run-9:gate:publish")
    assert stored is not None
    assert stored["status"] == "approved"


@pytest.mark.asyncio
async def test_every_gate_a_run_opened_stays_readable(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """A second approval must not erase the first one's record."""

    snapshot = _snapshot("run-1", status="waiting_human")
    first = {**_gate("run-1", status="approved", decided_by="carol")}
    first["gate_id"] = "run-1:gate:first"
    second = {**_gate("run-1")}
    second["gate_id"] = "run-1:gate:second"

    await projection.record(snapshot=snapshot, events=[], gates=[first, second])

    assert (await projection.get_gate("run-1:gate:first")) is not None
    assert (await projection.get_gate("run-1:gate:second")) is not None


@pytest.mark.asyncio
async def test_gates_for_run_returns_every_gate_the_run_opened_oldest_first(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """The only durable way to answer "who approved this Run" once its
    in-flight fields (`pending_gate_id`, `action_plan[].gate_id`) are gone."""

    snapshot = _snapshot("run-1", status="succeeded")
    first = {
        **_gate("run-1", status="rejected", created_at="2026-07-29T00:00:00+00:00"),
        "gate_id": "run-1:gate:first",
    }
    second = {
        **_gate("run-1", created_at="2026-07-29T00:05:00+00:00"),
        "gate_id": "run-1:gate:second",
    }

    await projection.record(snapshot=snapshot, events=[], gates=[first, second])
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


@pytest.mark.asyncio
async def test_gates_for_run_never_returns_another_runs_gate(
    projection: SqlAlchemyAuditProjection,
) -> None:
    await projection.record(
        snapshot=_snapshot("run-1"), events=[], gates=[_gate("run-1")]
    )
    await projection.record(
        snapshot=_snapshot("run-2"), events=[], gates=[_gate("run-2")]
    )

    gates = await projection.gates_for_run("run-1")

    assert [gate["gate_id"] for gate in gates] == ["run-1:gate:publish"]


@pytest.mark.asyncio
async def test_gates_for_run_is_empty_when_the_run_never_opened_one(
    projection: SqlAlchemyAuditProjection,
) -> None:
    await projection.record(snapshot=_snapshot("run-1"), events=[], gates=[])

    assert await projection.gates_for_run("run-1") == []


@pytest.mark.asyncio
async def test_gates_for_run_never_reports_a_forged_temporal_approval(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """`record` projects gates from the Workflow, an untrusted source for
    approval (see `_project_gate`); `gates_for_run` must read that same
    downgrade back, not the forged "approved" status."""

    forged = _gate("run-1", status="approved", decided_by="mallory")

    await projection.record(snapshot=_snapshot("run-1"), events=[], gates=[forged])

    gates = await projection.gates_for_run("run-1")

    assert gates[0]["status"] == "pending"
    assert gates[0]["decided_by"] is None


@pytest.mark.asyncio
async def test_listing_is_scoped_to_one_organization(
    projection: SqlAlchemyAuditProjection,
) -> None:
    await projection.record(
        snapshot=_snapshot("run-a", organization="org-a"), events=[], gates=[]
    )
    await projection.record(
        snapshot=_snapshot("run-b", organization="org-b"), events=[], gates=[]
    )

    page = await projection.list_runs(organization="org-a")

    assert [item["run_id"] for item in page["items"]] == ["run-a"]


@pytest.mark.asyncio
async def test_paging_the_whole_list_matches_reading_it_at_once(
    projection: SqlAlchemyAuditProjection,
) -> None:
    """Keyset paging must not drop or repeat a Run across page boundaries."""

    for index in range(11):
        await projection.record(
            snapshot=_snapshot(
                f"run-{index:02d}",
                created_at=f"2026-07-29T00:00:{index:02d}+00:00",
            ),
            events=[],
            gates=[],
        )

    whole = await projection.list_runs(organization="gaia", limit=50)
    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = await projection.list_runs(organization="gaia", limit=3, cursor=cursor)
        walked.extend(str(item["run_id"]) for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert walked == [str(item["run_id"]) for item in whole["items"]]
    assert len(walked) == len(set(walked)) == 11


@pytest.mark.asyncio
async def test_a_cursor_this_store_did_not_issue_is_rejected(
    projection: SqlAlchemyAuditProjection,
) -> None:
    with pytest.raises(InvalidRunCursor):
        await projection.list_runs(organization="gaia", cursor="not-a-cursor!!")


@pytest.mark.asyncio
async def test_filters_narrow_the_listing_without_leaking_other_organizations(
    projection: SqlAlchemyAuditProjection,
) -> None:
    await projection.record(
        snapshot=_snapshot("run-a", status="succeeded", scenario_id="ticket.prepare"),
        events=[],
        gates=[],
    )
    await projection.record(
        snapshot=_snapshot("run-b", status="blocked", scenario_id="ticket.prepare"),
        events=[],
        gates=[],
    )
    await projection.record(
        snapshot=_snapshot("run-c", status="succeeded", scenario_id="ticket.close"),
        events=[],
        gates=[],
    )

    by_status = await projection.list_runs(organization="gaia", status="succeeded")
    by_scenario = await projection.list_runs(
        organization="gaia", scenario_id="ticket.close"
    )

    assert {str(item["run_id"]) for item in by_status["items"]} == {"run-a", "run-c"}
    assert [str(item["run_id"]) for item in by_scenario["items"]] == ["run-c"]
