"""Execution Runtime contracts.

This module defines the abstract boundary consumed by Gaia's API layer.
Applications choose in-process development execution or Temporal durable orchestration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from gaia.contracts.models import (
    HumanGate,
    HumanGateDecisionRequest,
    RunEvent,
    RunPage,
    RunRequest,
    RunSnapshot,
    RunStatus,
)

RUN_LIST_DEFAULT_LIMIT = 50
RUN_LIST_MAX_LIMIT = 200


class RuntimeConflict(ValueError):
    """The requested operation conflicts with durable runtime state."""


class RuntimePermissionDenied(ValueError):
    """The caller cannot perform the requested runtime operation."""


class InvalidRunCursor(ValueError):
    """A Runtime list cursor is malformed or was not issued by that Runtime."""


class RuntimeRunNotFound(KeyError):
    """The durable execution provider has no record of this Run or Gate.

    Distinct from the provider being unreachable: "Temporal deleted this
    Workflow when its retention window closed" and "Temporal is down" are
    different facts, and only the first one may be answered from the audit
    projection alone. It subclasses `KeyError` so the API's existing
    not-found mapping turns it into a 404 rather than a 500.
    """


class AuditProjection(Protocol):
    """Durable evidence store for Runs, written by the active Runtime, read by Gaia.

    Temporal Workflow History is the execution source of truth *while a Run can
    still be replayed*. It is deleted when namespace retention closes, which
    makes it unfit to be the only record of what was approved, denied, or
    executed. This projection is the record that has to outlive it.

    Implementations exchange plain JSON-compatible dicts, not Pydantic models,
    because the writer is a Temporal Activity payload boundary.
    """

    async def record(
        self,
        *,
        snapshot: dict[str, object],
        events: list[dict[str, object]],
        gates: list[dict[str, object]],
    ) -> None:
        """Idempotently project one Run's current evidence. Safe to replay."""
        ...

    async def record_decision(
        self,
        *,
        gate: dict[str, object],
        decision: str,
        decided_by: str,
        comment: str | None,
        decided_at: datetime,
    ) -> bool:
        """Record an authenticated human decision on a gate.

        This is the only path that may grant approval. `record` projects gates
        from the Workflow, which is not a trusted source: Temporal namespace
        access would otherwise be enough to forge an approver.
        """
        ...

    async def get_run(self, run_id: str) -> dict[str, object] | None: ...

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: str | None = None,
        scenario_id: str | None = None,
        limit: int = ...,
        cursor: str | None = None,
    ) -> dict[str, object]: ...

    async def events_after(
        self, run_id: str, sequence: int = 0
    ) -> list[dict[str, object]]: ...

    async def get_gate(self, gate_id: str) -> dict[str, object] | None: ...

    async def gates_for_run(self, run_id: str) -> list[dict[str, object]]:
        """Every gate this Run ever opened, oldest first.

        `get_gate` answers "what is gate X" for a caller who already holds an
        id. This answers "what gates did Run Y open" for a caller who only
        holds the Run -- the query the Console's Run list and demo landing
        page need to attribute an approval to a Run without already knowing
        which gate id to ask for. Not scoped by organization: callers reach
        this through `authorized_run`, which already rejected a Run outside
        the caller's organization before this is ever called.
        """
        ...


class RuntimeEngine(Protocol):
    """Public runtime contract consumed by API and orchestration callers."""

    async def create(self, request: RunRequest, idempotency_key: str) -> RunSnapshot: ...

    async def decide(
        self,
        gate_id: str,
        body: HumanGateDecisionRequest,
    ) -> RunSnapshot: ...

    async def cancel(self, run_id: str, reason: str) -> RunSnapshot: ...

    async def inspect(self, run_id: str) -> RunSnapshot: ...

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = ...,
        cursor: str | None = None,
    ) -> RunPage: ...

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]: ...

    async def get_gate(self, gate_id: str) -> HumanGate: ...

    async def gates_for_run(self, run_id: str) -> list[HumanGate]:
        """Every gate this Run ever opened, oldest first. See `AuditProjection.gates_for_run`."""
        ...
