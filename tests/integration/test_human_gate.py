from datetime import UTC, datetime, timedelta

import pytest

from gaia.contracts.models import Decision, GateStatus, HumanGate, RiskLevel
from gaia.runtime.human_gates import GateDecisionConflict, GatePermissionDenied, decide_gate


def make_gate() -> HumanGate:
    now = datetime.now(UTC)
    return HumanGate(
        gate_id="g",
        run_id="r",
        command_id="c",
        reason="high risk",
        risk_level=RiskLevel.HIGH,
        requested_action={},
        status=GateStatus.PENDING,
        requested_by="requester",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_gate_requires_distinct_approver_and_is_immutable_after_decision() -> None:
    with pytest.raises(GatePermissionDenied):
        decide_gate(
            make_gate(),
            decision=Decision.APPROVED,
            decided_by="requester",
            roles=["approver"],
            comment="x",
            now=datetime.now(UTC),
        )
    decided = decide_gate(
        make_gate(),
        decision=Decision.APPROVED,
        decided_by="a",
        roles=["approver"],
        comment="x",
        now=datetime.now(UTC),
    )
    assert decided.status == GateStatus.APPROVED
    with pytest.raises(GateDecisionConflict):
        decide_gate(
            decided,
            decision=Decision.REJECTED,
            decided_by="b",
            roles=["approver"],
            comment="x",
            now=datetime.now(UTC),
        )
