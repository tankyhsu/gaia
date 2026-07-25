from pathlib import Path

from examples.controlled_task import create_controlled_task_composition
from examples.controlled_task.workflow import (
    build_controlled_task_graph,
    create_sqlite_checkpointer,
)
from gaia.contracts.models import HumanGateDecisionRequest, RunRequest
from gaia.persistence.database import initialize_database
from gaia.runtime.recovery import recover_runtime


async def test_waiting_run_resumes_with_a_new_runtime_instance(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/recovery.db")
    request = RunRequest.model_validate(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {"id": "u", "organization": "org-alpha", "roles": ["operator"]},
            "request": {"text": "pause res-001 because x"},
        }
    )
    checkpoint_path = tmp_path / "workflow.db"
    first_composition = create_controlled_task_composition(
        workflow=build_controlled_task_graph(create_sqlite_checkpointer(checkpoint_path)),
    )
    first_runtime = first_composition.create_runtime(factory)
    waiting = await first_runtime.create(request, "12345678")

    restarted_runtime = create_controlled_task_composition(
        resources=first_composition.resources,
        workflow=build_controlled_task_graph(create_sqlite_checkpointer(checkpoint_path)),
    ).create_runtime(factory)
    assert waiting.run_id in await recover_runtime(restarted_runtime)
    completed = await restarted_runtime.decide(
        waiting.pending_gate_id or "",
        HumanGateDecisionRequest(
            decision="approved",
            decided_by="approver",
            roles=["approver"],
            comment="approved after restart",
        ),
    )

    assert completed.status.value == "succeeded"
    assert restarted_runtime.side_effect_success_count == 1
