"""Real Temporal coverage for FunctionScenarioRunner agent handoffs."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gaia import ScenarioContext, ScenarioResponse, scenario, write_tool
from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import (
    Decision,
    HumanGateDecisionRequest,
    RiskLevel,
    RunMode,
    RunRequest,
    RunSnapshot,
    RunStatus,
    UserIdentity,
    WriteMode,
)
from gaia.runtime.dependencies import RuntimeDependencies, ToolRegistry
from gaia.runtime.function_runner import FunctionScenarioRunner
from gaia.runtime.function_tools import function_tool
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


async def _wait_for_status(
    runtime: TemporalRuntimeEngine,
    run_id: str,
    expected: RunStatus,
) -> RunSnapshot:
    for _ in range(100):
        snapshot = await runtime.inspect(run_id)
        if snapshot.status == expected:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected.value}")


@pytest.mark.external
@pytest.mark.asyncio
async def test_real_temporal_handoff_enters_human_gate_and_executes_command() -> None:
    """Prove handoff state, approval, and the write share one Workflow History."""

    writes: dict[str, dict[str, Any]] = {}

    async def reconcile(*, idempotency_key: str) -> dict[str, Any] | None:
        return writes.get(idempotency_key)

    @write_tool(
        "access.grant",
        risk_level=RiskLevel.HIGH,
        required_roles=("employee",),
        reconcile=reconcile,
    )
    async def grant_access(
        system: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = {"system": system, "status": "granted"}
        writes[idempotency_key] = result
        return result

    @scenario(
        "access.prepare",
        allowed_tools=("access.grant",),
        recognized_roles=("employee",),
        write_mode=WriteMode.ENABLED,
        max_steps=4,
        max_model_calls=0,
    )
    async def coordinator(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.handoff_to(
            "policy",
            input={"system": "finance"},
            reason="check access policy",
            state_updates={"requester": context.request.user.id},
        )

    async def policy_agent(context: ScenarioContext) -> ScenarioResponse:
        assert context.agent_id == "policy"
        assert context.shared_state["requester"] == "employee-1"
        return ScenarioResponse.handoff_to(
            "executor",
            input=context.handoff_input,
            reason="policy check passed",
            state_updates={"policy": "least-privilege"},
        )

    async def executor_agent(context: ScenarioContext) -> ScenarioResponse:
        assert context.agent_id == "executor"
        assert context.shared_state["policy"] == "least-privilege"
        assert context.tools is not None
        return ScenarioResponse.propose(
            context.tools.propose(
                grant_access,
                step_id="grant-access",
                payload={"system": context.handoff_input["system"]},
                reason="Grant access after policy review",
            ),
            pending_result={"review": "complete"},
        )

    registry = ToolRegistry((function_tool(grant_access),))
    audit = InMemoryAuditProjection()
    dependencies = RuntimeDependencies(
        runners={
            "access.prepare": FunctionScenarioRunner(
                coordinator,
                tools=registry,
                handoff_handlers={
                    "policy": policy_agent,
                    "executor": executor_agent,
                },
                allowed_handoffs={
                    "scenario": ("policy",),
                    "policy": ("executor",),
                },
            )
        },
        write_tools=registry,
        audit_projection=audit,
    )
    task_queue = f"gaia-handoff-{uuid4()}"
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

        runtime = TemporalRuntimeEngine(
            execution=execution,
            backend=TemporalClientBackend(execution, client_factory=client_factory),
            dependencies=dependencies,
            audit_projection=audit,
        )
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflow_runner=gaia_workflow_runner(),
            workflows=(GaiaRuntimeWorkflow,),
            activities=runtime.activity_handlers(),
        ):
            initial = await runtime.create(
                RunRequest(
                    scenario_id="access.prepare",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="employee-1",
                        organization="gaia",
                        roles=["employee"],
                    ),
                    request={"text": "prepare access"},
                ),
                "temporal-real-handoff-gate",
            )
            waiting = await _wait_for_status(
                runtime,
                initial.run_id,
                RunStatus.WAITING_HUMAN,
            )
            assert waiting.pending_gate_id is not None
            assert waiting.pending_result == {"review": "complete"}
            events = await runtime.events_after(waiting.run_id)
            assert [event.step for event in events].count("agent_handoff") == 2

            await runtime.decide(
                waiting.pending_gate_id,
                HumanGateDecisionRequest(
                    decision=Decision.APPROVED,
                    decided_by="approver-1",
                    roles=["approver"],
                    comment="approved",
                ),
            )
            handle = environment.client.get_workflow_handle(initial.run_id)
            await handle.result()
            completed = await runtime.inspect(initial.run_id)

    assert completed.status == RunStatus.SUCCEEDED
    assert completed.result == {"review": "complete"}
    assert completed.pending_gate_id is None
    assert list(writes.values()) == [{"system": "finance", "status": "granted"}]
