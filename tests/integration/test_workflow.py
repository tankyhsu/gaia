from pathlib import Path

from langgraph.types import Command

from examples.controlled_task.workflow import (
    build_controlled_task_graph,
    create_sqlite_checkpointer,
)


def _write_state() -> dict[str, object]:
    return {
        "run_id": "run-workflow",
        "request_text": "pause res-001 because maintenance",
        "intent": {
            "operation": "set_status",
            "resource_id": "res-001",
            "target_status": "paused",
            "reason": "maintenance",
        },
        "user": {"id": "operator", "organization": "org-alpha", "roles": ["operator"]},
        "resource": {
            "resource_id": "res-001",
            "organization": "org-alpha",
            "status": "active",
            "readable_roles": ["reader", "operator"],
        },
        "context_gaps": [],
        "gate_id": "gate-1",
        "visited": [],
    }


def test_workflow_routes_read_without_visiting_write_nodes() -> None:
    graph = build_controlled_task_graph()
    state = _write_state()
    state["intent"] = {"operation": "inspect", "resource_id": "res-001"}
    state["user"] = {"id": "reader", "organization": "org-alpha", "roles": ["reader"]}
    result = graph.invoke(state)
    assert result["outcome"] == "read"
    assert "return_read_result" in result["visited"]
    assert "create_human_gate" not in result["visited"]


def test_workflow_interrupts_and_resumes_from_sqlite_checkpoint(tmp_path: Path) -> None:
    graph = build_controlled_task_graph(create_sqlite_checkpointer(tmp_path / "workflow.db"))
    config = {"configurable": {"thread_id": "run-workflow"}}
    paused = graph.invoke(_write_state(), config)
    assert paused["outcome"] == "approval"
    assert "propose_side_effect" in paused["visited"]
    assert "execute_side_effect" not in paused["visited"]

    resumed = graph.invoke(Command(resume={"decision": "approved"}), config)
    assert resumed["approval_decision"] == "approved"
    assert "create_human_gate" in resumed["visited"]
    assert "execute_side_effect" in resumed["visited"]
    assert resumed["visited"][-1] == "finalize"
