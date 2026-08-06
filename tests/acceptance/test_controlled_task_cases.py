from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from examples.controlled_task import create_controlled_task_composition
from examples.controlled_task.read_tool import DEFAULT_RESOURCES
from examples.controlled_task.write_tool import MockResourceWriteAdapter
from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import (
    HumanGateDecisionRequest,
    RunRequest,
    RunSnapshot,
    RunStatus,
    ToolResult,
)
from gaia.runtime.temporal_backend import TemporalClient, TemporalClientBackend
from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.runtime.temporal_worker import gaia_workflow_runner
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow
from gaia.testing import InMemoryAuditProjection

CASES_PATH = (
    Path(__file__).parents[2]
    / "examples"
    / "controlled_task"
    / "specs"
    / "acceptance-cases.json"
)
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text())["cases"]


class CountingWriteAdapter:
    definition = MockResourceWriteAdapter.definition

    def __init__(
        self,
        resources: dict[str, dict[str, Any]],
        mode: str,
        successes: list[str],
    ) -> None:
        self._delegate = MockResourceWriteAdapter(resources, mode)
        self._successes = successes

    async def execute(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ToolResult:
        result = await self._delegate.execute(
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if result.ok:
            self._successes.append(idempotency_key)
        return result

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None:
        return await self._delegate.reconcile(idempotency_key=idempotency_key)


def _contains(actual: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if not expected:
        return True
    return actual is not None and all(
        actual.get(key) == value for key, value in expected.items()
    )


async def _wait_until_settled(
    runtime: TemporalRuntimeEngine,
    run_id: str,
) -> RunSnapshot:
    for _ in range(200):
        snapshot = await runtime.inspect(run_id)
        if snapshot.status != RunStatus.RUNNING:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not settle")


@pytest.mark.external
@pytest.mark.parametrize("case", CASES, ids=[case["case_id"] for case in CASES])
async def test_controlled_task_acceptance_case(case: dict[str, Any]) -> None:
    resources = {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
    successes: list[str] = []

    def adapter_factory(payload: dict[str, Any]) -> CountingWriteAdapter:
        return CountingWriteAdapter(
            resources,
            str(payload.get("write_adapter_mode", "normal")),
            successes,
        )

    audit = InMemoryAuditProjection()
    composition = create_controlled_task_composition(
        resources=resources,
        write_adapter_factory=adapter_factory,
        audit_projection=audit,
    )
    task_queue = f"gaia-controlled-task-{uuid4()}"
    execution = RuntimeExecutionSettings(task_queue=task_queue)

    async with await WorkflowEnvironment.start_local(
        search_attributes=(
            GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
            GAIA_SCENARIO_SEARCH_ATTRIBUTE,
            GAIA_STATUS_SEARCH_ATTRIBUTE,
        )
    ) as environment:

        async def client_factory() -> TemporalClient:
            return environment.client

        def new_runtime() -> TemporalRuntimeEngine:
            return TemporalRuntimeEngine(
                execution=execution,
                backend=TemporalClientBackend(
                    execution,
                    client_factory=client_factory,
                ),
                dependencies=composition.dependencies,
                audit_projection=audit,
            )

        runtime = new_runtime()
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

        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflow_runner=gaia_workflow_runner(),
            workflows=(GaiaRuntimeWorkflow,),
            activities=runtime.activity_handlers(),
        ):
            snapshot = await runtime.create(request, case["idempotency_key"])
            initial_run_id = snapshot.run_id
            handle = environment.client.get_workflow_handle(initial_run_id)

            for action in case.get("actions", []):
                if action["type"] == "restart_runtime":
                    runtime = new_runtime()
                elif action["type"] == "human_decision":
                    snapshot = await _wait_until_settled(runtime, initial_run_id)
                    snapshot = await runtime.decide(
                        snapshot.pending_gate_id or "",
                        HumanGateDecisionRequest.model_validate(
                            {
                                key: value
                                for key, value in action.items()
                                if key != "type"
                            }
                        ),
                    )
                elif action["type"] == "repeat_create_request":
                    await handle.result()
                    for _ in range(action["count"]):
                        repeated = await runtime.create(
                            request,
                            case["idempotency_key"],
                        )
                        assert repeated.run_id == initial_run_id
                        snapshot = repeated
                else:  # pragma: no cover - repository-controlled fixture
                    raise AssertionError(
                        f"unknown acceptance action: {action['type']}"
                    )

            await handle.result()
            snapshot = await runtime.inspect(initial_run_id)

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
            assert len(successes) == expected["side_effect_success_count"]

            if expected.get("same_run_id_for_repeated_create"):
                repeated_snapshot = await runtime.create(
                    request,
                    case["idempotency_key"],
                )
                assert repeated_snapshot.run_id == initial_run_id
