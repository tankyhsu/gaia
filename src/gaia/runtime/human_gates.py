"""Human gate decision rules owned by Execution Runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from gaia.contracts.models import Decision, GateStatus, HumanGate


class GateDecisionConflict(ValueError):
    pass


class GatePermissionDenied(ValueError):
    pass


def expire_if_needed(gate: HumanGate, now: datetime) -> HumanGate:
    if gate.status == GateStatus.PENDING and now.astimezone(UTC) >= gate.expires_at:
        return gate.model_copy(update={"status": GateStatus.EXPIRED})
    return gate


def decide_gate(
    gate: HumanGate,
    *,
    decision: Decision,
    decided_by: str,
    roles: list[str],
    comment: str,
    now: datetime,
) -> HumanGate:
    gate = expire_if_needed(gate, now)
    if gate.status != GateStatus.PENDING:
        if gate.decided_by == decided_by and gate.status.value == decision.value:
            return gate
        raise GateDecisionConflict(gate.gate_id)
    if decided_by == gate.requested_by or "approver" not in roles:
        raise GatePermissionDenied(gate.gate_id)
    status = GateStatus.APPROVED if decision == Decision.APPROVED else GateStatus.REJECTED
    return gate.model_copy(
        update={"status": status, "decided_by": decided_by, "comment": comment, "decided_at": now}
    )
