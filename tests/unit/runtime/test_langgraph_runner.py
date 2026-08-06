from __future__ import annotations

from typing import Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from gaia.contracts.models import (
    ExecutionPolicy,
    RiskLevel,
    RunMode,
    RunRequest,
    RunStatus,
    UserIdentity,
    VersionBundle,
    WriteMode,
)
from gaia.runtime import (
    LANGGRAPH_CONTINUATION,
    LangGraphScenarioRunner,
    RuntimeContinuation,
    RuntimeOutcome,
    SideEffectProposal,
)


class PlanState(TypedDict, total=False):
    phase: str
    resource_id: str
    action_result: dict[str, Any]


def _graph() -> Any:
    async def advance(state: PlanState) -> dict[str, object]:
        return {
            "phase": "complete" if state.get("action_result") else "write",
        }

    builder = StateGraph(PlanState)
    builder.add_node("advance", advance)
    builder.add_edge(START, "advance")
    builder.add_edge("advance", END)
    return builder.compile()


def _outcome(state: dict[str, Any]) -> RuntimeOutcome:
    if state["phase"] == "write":
        return RuntimeOutcome(
            status=RunStatus.RUNNING,
            side_effect=SideEffectProposal(
                step_id="publish",
                tool_name="publish-resource",
                payload={"resource_id": state["resource_id"]},
                reason="Publish the resource",
                risk_level=RiskLevel.HIGH,
            ),
        )
    return RuntimeOutcome(
        status=RunStatus.SUCCEEDED,
        result=dict(state["action_result"]),
    )


def _runner() -> LangGraphScenarioRunner:
    return LangGraphScenarioRunner(
        graph=_graph(),
        execution_policy=ExecutionPolicy(
            policy_id="graph-policy",
            version="1",
            scenario_id="graph.publish",
            allowed_tools=["publish-resource"],
            recognized_roles=["operator"],
            max_steps=5,
            max_duration_seconds=30,
            max_model_calls=0,
            write_mode=WriteMode.APPROVAL_REQUIRED,
            human_gate_rules=[],
        ),
        version_bundle=VersionBundle(
            policy="policy:1",
            workflow="graph:1",
            rules="rules:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        ),
        initial_state=lambda run_id, request: {
            "phase": "start",
            "resource_id": request.request.text,
        },
        outcome_from_state=_outcome,
    )


def _request() -> RunRequest:
    return RunRequest(
        scenario_id="graph.publish",
        mode=RunMode.MOCK,
        user=UserIdentity(
            id="operator-1",
            organization="gaia",
            roles=["operator"],
        ),
        request={"text": "resource-1"},
    )


@pytest.mark.asyncio
async def test_graph_emits_one_side_effect_then_resumes_from_temporal_state() -> None:
    runner = _runner()

    proposed = await runner.run(run_id="run-1", request=_request())

    assert proposed.side_effect is not None
    assert proposed.side_effect.payload == {"resource_id": "resource-1"}
    assert proposed.continuation is not None
    assert proposed.continuation.handler == LANGGRAPH_CONTINUATION
    assert proposed.continuation.input["state"]["phase"] == "write"

    completed = await runner.run_continuation(
        run_id="run-1",
        request=_request(),
        continuation=RuntimeContinuation(
            handler=proposed.continuation.handler,
            input=proposed.continuation.input,
            action_result={"resource_id": "resource-1", "status": "published"},
        ),
    )

    assert completed.status == RunStatus.SUCCEEDED
    assert completed.result == {
        "resource_id": "resource-1",
        "status": "published",
    }


@pytest.mark.asyncio
async def test_graph_state_must_be_temporal_payload_safe() -> None:
    runner = LangGraphScenarioRunner(
        graph=_graph(),
        execution_policy=_runner().execution_policy,
        version_bundle=_runner().version_bundle,
        initial_state=lambda run_id, request: {"unsafe": object()},
        outcome_from_state=_outcome,
    )

    with pytest.raises(ValueError, match="JSON serializable"):
        await runner.run(run_id="run-1", request=_request())
