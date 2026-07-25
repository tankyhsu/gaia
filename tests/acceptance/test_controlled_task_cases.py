from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from examples.controlled_task import create_controlled_task_composition
from gaia.contracts.models import HumanGateDecisionRequest, RunRequest, RunSnapshot
from gaia.persistence.database import initialize_database

CASES_PATH = (
    Path(__file__).parents[2] / "examples" / "controlled_task" / "specs" / "acceptance-cases.json"
)
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text())["cases"]


def _contains(actual: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if not expected:
        return True
    return actual is not None and all(actual.get(key) == value for key, value in expected.items())


@pytest.mark.parametrize("case", CASES, ids=[case["case_id"] for case in CASES])
async def test_controlled_task_acceptance_case(case: dict[str, Any], tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/{case['case_id']}.db")
    resources: dict[str, dict[str, Any]] | None = None
    composition = create_controlled_task_composition(resources=resources)
    runtime = composition.create_runtime(factory)
    request = RunRequest.model_validate(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": case["user"],
            "request": {
                "text": case["request_text"],
                "metadata": case.get("setup", {}),
            },
        }
    )
    snapshot = await runtime.create(request, case["idempotency_key"])
    initial_run_id = snapshot.run_id

    for action in case.get("actions", []):
        if action["type"] == "restart_runtime":
            resources = composition.resources
            composition = create_controlled_task_composition(resources=resources)
            runtime = composition.create_runtime(factory)
        elif action["type"] == "human_decision":
            snapshot = await runtime.decide(
                snapshot.pending_gate_id or "",
                HumanGateDecisionRequest.model_validate(
                    {key: value for key, value in action.items() if key != "type"}
                ),
            )
        elif action["type"] == "repeat_create_request":
            for _ in range(action["count"]):
                repeated = await runtime.create(request, case["idempotency_key"])
                assert repeated.run_id == initial_run_id
                snapshot = repeated
        else:  # pragma: no cover - fixture schema is controlled in the repository
            raise AssertionError(f"unknown acceptance action: {action['type']}")

    expected = case["expected"]
    assert snapshot.status.value == expected["status"]
    actual_error = snapshot.error.code if snapshot.error else None
    assert actual_error == expected["error_code"]
    assert _contains(snapshot.result, expected["result_contains"])

    events = await runtime.events_after(snapshot.run_id)
    steps = {event.step for event in events}
    rule_refs = {rule for event in events for rule in event.rule_refs}
    assert set(expected["required_steps"]) <= steps
    assert not set(expected["forbidden_steps"]).intersection(steps)
    assert set(expected["required_rule_refs"]) <= rule_refs
    assert runtime.side_effect_success_count == expected["side_effect_success_count"]

    if expected.get("same_run_id_for_repeated_create"):
        repeated_snapshot: RunSnapshot = await runtime.create(request, case["idempotency_key"])
        assert repeated_snapshot.run_id == initial_run_id
