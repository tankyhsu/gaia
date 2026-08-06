"""An in-memory `AuditProjection` for tests that need a Worker, not a database.

This double proves *wiring* -- that a Workflow reaches `record_audit` and that
the payload is well-formed. It deliberately does not prove durability, replay
safety, or ordering: those are properties of the SQL queries, and they are
tested against the real store in `tests/unit/persistence/test_audit_projection.py`
and against a real Temporal server in `tests/integration/test_temporal_end_to_end.py`.

Do not grow this class to mirror the production store. Two implementations of
the same semantics is exactly the drift the projection exists to avoid.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from gaia.runtime.contracts import RUN_LIST_DEFAULT_LIMIT


class InMemoryAuditProjection:
    """Keeps whatever it was handed, in the order it was handed it."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[int, dict[str, Any]]] = {}
        self.gates: dict[str, dict[str, Any]] = {}

    async def record(
        self,
        *,
        snapshot: dict[str, Any],
        events: list[dict[str, Any]],
        gates: list[dict[str, Any]],
    ) -> None:
        run_id = str(snapshot["run_id"])
        self.runs[run_id] = dict(snapshot)
        stored = self.events.setdefault(run_id, {})
        for event in events:
            stored.setdefault(int(event["sequence"]), dict(event))
        for gate in gates:
            self._project_gate(dict(gate))

    def _project_gate(self, gate: dict[str, Any]) -> None:
        """Mirror the real store's rule: the Workflow cannot grant approval.

        This double is weaker than useless if it accepts what
        `SqlAlchemyAuditProjection` refuses -- a test proving a forged Temporal
        Update is rejected would pass here while production stayed open.
        """

        gate_id = str(gate["gate_id"])
        status = str(gate["status"])
        if status == "approved":
            gate |= {"status": "pending", "decided_by": None, "decided_at": None}
            status = "pending"
        existing = self.gates.get(gate_id)
        if existing is None:
            self.gates[gate_id] = gate
            return
        if existing["status"] != "pending" or status in {"pending", "approved"}:
            return
        self.gates[gate_id] = gate

    async def record_decision(
        self,
        *,
        gate: dict[str, Any],
        decision: str,
        decided_by: str,
        comment: str | None,
        decided_at: datetime,
    ) -> bool:
        gate_id = str(gate["gate_id"])
        stored = self.gates.get(gate_id)
        if stored is not None and stored["status"] != "pending":
            return stored["status"] == decision and stored.get("decided_by") == decided_by
        decided = dict(stored if stored is not None else gate)
        decided |= {
            "status": decision,
            "decided_by": decided_by,
            "comment": comment,
            "decided_at": decided_at.isoformat(),
        }
        self.gates[gate_id] = decided
        return True

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: str | None = None,
        scenario_id: str | None = None,
        limit: int = RUN_LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        del cursor
        items = [
            run
            for run in self.runs.values()
            if (organization is None or run.get("user", {}).get("organization") == organization)
            and (status is None or run.get("status") == status)
            and (scenario_id is None or run.get("scenario_id") == scenario_id)
        ]
        items.sort(key=lambda run: str(run.get("created_at", "")), reverse=True)
        return {"items": items[:limit], "next_cursor": None}

    async def events_after(
        self, run_id: str, sequence: int = 0
    ) -> list[dict[str, Any]]:
        stored = self.events.get(run_id, {})
        return [stored[key] for key in sorted(stored) if key > sequence]

    async def get_gate(self, gate_id: str) -> dict[str, Any] | None:
        return self.gates.get(gate_id)

    async def gates_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Mirror the real store's `ix_audit_human_gates_run` ordering: oldest first.

        Kept behaviourally identical to `SqlAlchemyAuditProjection.gates_for_run`
        on purpose -- a double that returned, say, insertion order instead of
        `created_at` order would let a test relying on ordering pass here and
        fail against the real store.
        """

        matches = [gate for gate in self.gates.values() if gate.get("run_id") == run_id]
        matches.sort(key=lambda gate: str(gate.get("created_at", "")))
        return matches
