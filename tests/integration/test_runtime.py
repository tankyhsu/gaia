from pathlib import Path

from examples.controlled_task import create_controlled_task_composition
from gaia.contracts.models import HumanGateDecisionRequest, RunRequest
from gaia.persistence.database import initialize_database


async def test_runtime_waits_then_executes_approved_write(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/runtime.db")
    engine = create_controlled_task_composition().create_runtime(factory)
    request = RunRequest.model_validate(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {"id": "u", "organization": "org-alpha", "roles": ["operator"]},
            "request": {"text": "pause res-001 because x"},
        }
    )
    waiting = await engine.create(request, "12345678")
    result = await engine.decide(
        waiting.pending_gate_id or "",
        HumanGateDecisionRequest(
            decision="approved",
            decided_by="a",
            roles=["approver"],
            comment="yes",
        ),
    )
    assert result.status.value == "succeeded"
    assert result.result and result.result["status"] == "paused"
    assert engine.side_effect_success_count == 1
