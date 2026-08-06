"""Real Temporal Server + Worker integration coverage for Gaia Runtime."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gaia import (
    ScenarioContext,
    ScenarioResponse,
    ScenarioSideEffect,
    scenario,
    write_tool,
)
from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import (
    ApprovalView,
    Decision,
    ErrorCode,
    ExecutionPolicy,
    HumanGateDecisionRequest,
    RiskLevel,
    RunMode,
    RunRequest,
    RunSnapshot,
    RunStatus,
    UserIdentity,
    VersionBundle,
    WriteMode,
    WriteRecoveryStrategy,
)
from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.runtime.dependencies import (
    RuntimeDependencies,
    RuntimeOutcome,
    SideEffectProposal,
    ToolRegistry,
)
from gaia.runtime.function_runner import FunctionScenarioRunner
from gaia.runtime.function_tools import function_tool
from gaia.runtime.langgraph_runner import LangGraphScenarioRunner
from gaia.runtime.temporal_backend import TemporalClient, TemporalClientBackend
from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.runtime.temporal_worker import gaia_workflow_runner
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow


@pytest.fixture
async def audit(tmp_path: Path):
    """A real projection on disk -- the store has to outlive the Temporal server."""

    url = f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}"
    factory = await initialize_database(url)
    try:
        yield SqlAlchemyAuditProjection(factory)
    finally:
        await dispose_session_factory(factory)


HISTORY_FIXTURES = Path(__file__).parent / "histories"


async def _capture_history(environment: WorkflowEnvironment, run_id: str, name: str) -> None:
    """Record this Workflow's history as a replay fixture, when asked to.

    Off by default: capture rewrites files that `test_workflow_replay.py` uses
    to detect non-deterministic Workflow changes, so it has to be a deliberate
    act (`make capture-histories`) rather than a side effect of running tests.
    """

    if os.environ.get("GAIA_CAPTURE_HISTORIES") != "1":
        return
    history = await environment.client.get_workflow_handle(run_id).fetch_history()
    HISTORY_FIXTURES.mkdir(exist_ok=True)
    (HISTORY_FIXTURES / f"{name}.json").write_text(history.to_json(), encoding="utf-8")


async def _wait_for_projected_gate(
    audit: SqlAlchemyAuditProjection,
    gate_id: str,
) -> dict[str, Any]:
    """Wait for the gate to reach the projection.

    The Workflow's status flips to `waiting_human` in the same Workflow task
    that schedules the audit Activity, so a Temporal Query can see the gate
    before Gaia's database does. That lag is by design and bounded by one
    Activity round-trip -- `record_decision` takes the gate document precisely
    so an approver acting inside that window is not refused.
    """

    for _ in range(200):
        gate = await audit.get_gate(gate_id)
        if gate is not None:
            return gate
        await asyncio.sleep(0.01)
    raise AssertionError(f"gate {gate_id} never reached the audit projection")


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
async def test_real_temporal_server_worker_executes_scenario_activity(
    audit: SqlAlchemyAuditProjection,
) -> None:
    """Prove the production chain without the legacy SQL Runtime or a fake backend."""

    @scenario("temporal.e2e.read", max_model_calls=0)
    async def read_scenario(context: ScenarioContext) -> dict[str, object]:
        return {"message": f"Temporal executed {context.text}"}

    runner = FunctionScenarioRunner(read_scenario)
    dependencies = RuntimeDependencies(
        runners={"temporal.e2e.read": runner},
        write_tools=ToolRegistry(),
        audit_projection=audit,
    )
    task_queue = f"gaia-e2e-{uuid4()}"
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
            backend=TemporalClientBackend(
                execution,
                client_factory=client_factory,
            ),
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
                    scenario_id="temporal.e2e.read",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="developer",
                        organization="gaia",
                        roles=["user"],
                    ),
                    request={"text": "a real Activity"},
                ),
                "temporal-real-e2e",
            )
            assert initial.status == RunStatus.RUNNING
            handle = environment.client.get_workflow_handle(initial.run_id)
            await handle.result()
            snapshot = await runtime.inspect(initial.run_id)
            await _capture_history(environment, initial.run_id, "read_only_scenario")

    assert snapshot.status == RunStatus.SUCCEEDED
    assert snapshot.result == {"message": "Temporal executed a real Activity"}
    assert snapshot.pending_gate_id is None


@pytest.mark.external
@pytest.mark.asyncio
async def test_real_temporal_human_gate_approves_command_activity(
    audit: SqlAlchemyAuditProjection,
) -> None:
    """Prove durable approval gates and writes execute inside Temporal."""

    resources = {"widget-1": "draft"}
    executions: list[str] = []

    @write_tool(
        "temporal.e2e.publish",
        risk_level=RiskLevel.HIGH,
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )
    async def publish(resource_id: str, *, idempotency_key: str) -> dict[str, object]:
        executions.append(idempotency_key)
        resources[resource_id] = "published"
        return {"resource_id": resource_id, "status": "published"}

    @scenario(
        "temporal.e2e.write",
        allowed_tools=("temporal.e2e.publish",),
        max_model_calls=0,
        write_mode=WriteMode.ENABLED,
    )
    async def write_scenario(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.propose(
            ScenarioSideEffect(
                step_id="publish",
                tool_name="temporal.e2e.publish",
                payload={"resource_id": context.text},
                reason="Publishing changes a durable business record.",
                risk_level=RiskLevel.HIGH,
                approval_view=ApprovalView(
                    title="Publish widget",
                    summary="Move the widget to published.",
                    fields={"resource_id": context.text},
                    risk_explanation="This changes durable business state.",
                ),
            ),
            pending_result={"resource_id": context.text, "status": "published"},
        )

    registry = ToolRegistry((function_tool(publish),))
    runner = FunctionScenarioRunner(write_scenario, tools=registry)
    dependencies = RuntimeDependencies(
        runners={"temporal.e2e.write": runner},
        write_tools=registry,
        audit_projection=audit,
    )
    task_queue = f"gaia-e2e-{uuid4()}"
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
                    scenario_id="temporal.e2e.write",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="developer",
                        organization="gaia",
                        roles=["user"],
                    ),
                    request={"text": "widget-1"},
                ),
                "temporal-real-gate-command",
            )
            waiting = await _wait_for_status(
                runtime,
                initial.run_id,
                RunStatus.WAITING_HUMAN,
            )
            assert resources["widget-1"] == "draft"
            assert executions == []
            gate_id = waiting.pending_gate_id
            assert gate_id is not None

            approved = await runtime.decide(
                gate_id,
                HumanGateDecisionRequest(
                    decision=Decision.APPROVED,
                    decided_by="approver-1",
                    roles=["approver"],
                    comment="Approved by real Temporal integration test.",
                ),
            )
            assert approved.status in {RunStatus.RUNNING, RunStatus.WAITING_HUMAN}

            handle = environment.client.get_workflow_handle(initial.run_id)
            await handle.result()
            final = await runtime.inspect(initial.run_id)
            await _capture_history(environment, initial.run_id, "human_gate_approved")

    assert final.status == RunStatus.SUCCEEDED
    assert final.result == {"resource_id": "widget-1", "status": "published"}
    assert final.pending_gate_id is None
    assert resources["widget-1"] == "published"
    assert len(executions) == 1


class GraphState(TypedDict, total=False):
    phase: str
    resource_id: str
    action_result: dict[str, Any]


@pytest.mark.external
@pytest.mark.asyncio
async def test_real_temporal_replays_worker_and_resumes_langgraph(
    audit: SqlAlchemyAuditProjection,
) -> None:
    """Prove LangGraph routing survives a Worker restart through Workflow History."""

    resources = {"graph-widget": "draft"}
    executions: list[str] = []
    graph_phases: list[str] = []

    @write_tool(
        "temporal.e2e.graph-publish",
        risk_level=RiskLevel.HIGH,
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )
    async def publish(resource_id: str, *, idempotency_key: str) -> dict[str, object]:
        executions.append(idempotency_key)
        resources[resource_id] = "published"
        return {"resource_id": resource_id, "status": "published"}

    async def advance(state: GraphState) -> dict[str, object]:
        graph_phases.append(state["phase"])
        return {
            "phase": "complete" if state.get("action_result") else "write",
        }

    builder = StateGraph(GraphState)
    builder.add_node("advance", advance)
    builder.add_edge(START, "advance")
    builder.add_edge("advance", END)
    graph = builder.compile()

    def outcome_from_state(state: dict[str, Any]) -> RuntimeOutcome:
        if state["phase"] == "write":
            return RuntimeOutcome(
                status=RunStatus.RUNNING,
                side_effect=SideEffectProposal(
                    step_id="publish",
                    tool_name="temporal.e2e.graph-publish",
                    payload={"resource_id": state["resource_id"]},
                    reason="Publish the resource selected by LangGraph.",
                    risk_level=RiskLevel.HIGH,
                    approval_view=ApprovalView(
                        title="Publish graph widget",
                        summary="Approve the LangGraph-proposed write.",
                        fields={"resource_id": state["resource_id"]},
                        risk_explanation="This changes durable business state.",
                    ),
                ),
            )
        return RuntimeOutcome(
            status=RunStatus.SUCCEEDED,
            result=dict(state["action_result"]),
            decision_step="langgraph_complete",
        )

    registry = ToolRegistry((function_tool(publish),))
    runner = LangGraphScenarioRunner(
        graph=graph,
        execution_policy=ExecutionPolicy(
            policy_id="temporal-langgraph-policy",
            version="1",
            scenario_id="temporal.e2e.langgraph",
            allowed_tools=["temporal.e2e.graph-publish"],
            recognized_roles=["operator"],
            max_steps=5,
            max_duration_seconds=30,
            max_model_calls=0,
            write_mode=WriteMode.APPROVAL_REQUIRED,
            human_gate_rules=[],
        ),
        version_bundle=VersionBundle(
            policy="temporal-langgraph-policy:1",
            workflow="langgraph:1",
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
        outcome_from_state=outcome_from_state,
    )
    dependencies = RuntimeDependencies(
        runners={"temporal.e2e.langgraph": runner},
        write_tools=registry,
        audit_projection=audit,
    )
    task_queue = f"gaia-e2e-{uuid4()}"
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
        worker_kwargs = {
            "task_queue": task_queue,
            "workflow_runner": gaia_workflow_runner(),
            "workflows": (GaiaRuntimeWorkflow,),
            "activities": runtime.activity_handlers(),
        }
        async with Worker(environment.client, **worker_kwargs):
            initial = await runtime.create(
                RunRequest(
                    scenario_id="temporal.e2e.langgraph",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="operator-1",
                        organization="gaia",
                        roles=["operator"],
                    ),
                    request={"text": "graph-widget"},
                ),
                "temporal-real-langgraph-replay",
            )
            waiting = await _wait_for_status(
                runtime,
                initial.run_id,
                RunStatus.WAITING_HUMAN,
            )
            gate_id = waiting.pending_gate_id
            assert gate_id is not None
            assert graph_phases == ["start"]
            assert executions == []

        # A fresh Worker must replay Workflow History without rerunning the
        # completed graph Activity, then continue from the durable graph state.
        async with Worker(environment.client, **worker_kwargs):
            await runtime.decide(
                gate_id,
                HumanGateDecisionRequest(
                    decision=Decision.APPROVED,
                    decided_by="approver-1",
                    roles=["approver"],
                    comment="Resume the graph after Worker restart.",
                ),
            )
            handle = environment.client.get_workflow_handle(initial.run_id)
            await handle.result()
            final = await runtime.inspect(initial.run_id)
            await _capture_history(environment, initial.run_id, "langgraph_continuation")

    assert final.status == RunStatus.SUCCEEDED
    assert final.result == {"resource_id": "graph-widget", "status": "published"}
    assert resources["graph-widget"] == "published"
    assert len(executions) == 1
    assert graph_phases == ["start", "write"]


@pytest.mark.external
@pytest.mark.asyncio
async def test_evidence_survives_temporal_forgetting_the_workflow(
    audit: SqlAlchemyAuditProjection,
) -> None:
    """The point of the projection: audit answers after Temporal cannot.

    Temporal deletes Workflow History when the namespace retention window
    closes -- seven days in Gaia's own production-like stack. This test models
    the far side of that boundary by shutting the whole Temporal server down and
    then asking the same questions an auditor asks: what ran, under which policy
    version, who approved the write, and what the event trail was.

    Before the projection existed, every one of these reads returned nothing.
    """

    resources = {"widget-9": "draft"}

    @write_tool(
        "temporal.audit.publish",
        risk_level=RiskLevel.HIGH,
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )
    async def publish(resource_id: str, *, idempotency_key: str) -> dict[str, object]:
        resources[resource_id] = "published"
        return {"resource_id": resource_id, "status": "published"}

    @scenario(
        "temporal.audit.write",
        allowed_tools=("temporal.audit.publish",),
        max_model_calls=0,
        write_mode=WriteMode.ENABLED,
    )
    async def write_scenario(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.propose(
            ScenarioSideEffect(
                step_id="publish",
                tool_name="temporal.audit.publish",
                payload={"resource_id": context.text},
                reason="Publishing changes a durable business record.",
                risk_level=RiskLevel.HIGH,
                approval_view=ApprovalView(
                    title="Publish widget",
                    summary="Move the widget to published.",
                    fields={"resource_id": context.text},
                    risk_explanation="This changes durable business state.",
                ),
            ),
            pending_result={"resource_id": context.text, "status": "published"},
        )

    registry = ToolRegistry((function_tool(publish),))
    runner = FunctionScenarioRunner(write_scenario, tools=registry)
    dependencies = RuntimeDependencies(
        runners={"temporal.audit.write": runner},
        write_tools=registry,
        audit_projection=audit,
    )
    task_queue = f"gaia-e2e-{uuid4()}"
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
                    scenario_id="temporal.audit.write",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="developer",
                        organization="gaia",
                        roles=["user"],
                    ),
                    request={"text": "widget-9"},
                ),
                "temporal-audit-survives",
            )
            run_id = initial.run_id
            waiting = await _wait_for_status(runtime, run_id, RunStatus.WAITING_HUMAN)
            gate_id = waiting.pending_gate_id
            assert gate_id is not None

            # A pending approval must already be durable: a Run can wait here for
            # the whole gate TTL, and an operator has to be able to see it.
            pending = await _wait_for_projected_gate(audit, gate_id)
            assert pending["status"] == "pending"

            await runtime.decide(
                gate_id,
                HumanGateDecisionRequest(
                    decision=Decision.APPROVED,
                    decided_by="approver-9",
                    roles=["approver"],
                    comment="Approved so the evidence has an approver.",
                ),
            )
            await environment.client.get_workflow_handle(run_id).result()
            live = await runtime.inspect(run_id)
            assert live.status == RunStatus.SUCCEEDED
            await _capture_history(environment, run_id, "audit_projection_write")

    # Temporal is gone. Everything below answers from Gaia's own database.
    archived = await runtime.inspect(run_id)
    assert archived.status == RunStatus.SUCCEEDED
    assert archived.result == {"resource_id": "widget-9", "status": "published"}
    assert archived.version_bundle == live.version_bundle

    gate = await runtime.get_gate(gate_id)
    assert gate.status.value == "approved"
    assert gate.decided_by == "approver-9"
    assert gate.comment == "Approved so the evidence has an approver."

    events = await runtime.events_after(run_id, 0)
    steps = [event.step for event in events]
    assert "create_human_gate" in steps
    assert "human_gate_approved" in steps
    assert "execute_side_effect" in steps
    assert [event.sequence for event in events] == sorted(
        event.sequence for event in events
    )

    page = await runtime.list_runs(organization="gaia")
    assert [item.run_id for item in page.items] == [run_id]

    # And the isolation the live path enforces is not lost in the archive.
    assert (await runtime.list_runs(organization="other-org")).items == []


@pytest.mark.external
@pytest.mark.asyncio
async def test_a_decision_sent_straight_to_temporal_cannot_authorize_a_write(
    audit: SqlAlchemyAuditProjection,
) -> None:
    """Temporal namespace access must not be equivalent to approver authority.

    The Workflow's `decide` Update believes the `roles` in its own payload,
    because a Workflow has no way to authenticate anyone. Gaia's API is what
    replaces those claims with the caller's authenticated identity -- so anyone
    who can reach the namespace directly can skip that and hand the Workflow
    `roles=["approver"]`.

    This test does exactly that, and asserts the thing that actually matters:
    the guarded write does not happen. The forged Update still moves the
    Workflow's internal state, and it is allowed to; what stops it is that
    `execute_command` verifies the approval against Gaia's own database, which
    a Temporal client cannot write to.
    """

    resources = {"widget-forge": "draft"}

    @write_tool(
        "temporal.forge.publish",
        risk_level=RiskLevel.HIGH,
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )
    async def publish(resource_id: str, *, idempotency_key: str) -> dict[str, object]:
        resources[resource_id] = "published"
        return {"resource_id": resource_id, "status": "published"}

    @scenario(
        "temporal.forge.write",
        allowed_tools=("temporal.forge.publish",),
        max_model_calls=0,
        write_mode=WriteMode.ENABLED,
    )
    async def write_scenario(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.propose(
            ScenarioSideEffect(
                step_id="publish",
                tool_name="temporal.forge.publish",
                payload={"resource_id": context.text},
                reason="Publishing changes a durable business record.",
                risk_level=RiskLevel.HIGH,
                approval_view=ApprovalView(
                    title="Publish widget",
                    summary="Move the widget to published.",
                    fields={"resource_id": context.text},
                    risk_explanation="This changes durable business state.",
                ),
            ),
        )

    registry = ToolRegistry((function_tool(publish),))
    runner = FunctionScenarioRunner(write_scenario, tools=registry)
    dependencies = RuntimeDependencies(
        runners={"temporal.forge.write": runner},
        write_tools=registry,
        audit_projection=audit,
    )
    task_queue = f"gaia-e2e-{uuid4()}"
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
                    scenario_id="temporal.forge.write",
                    mode=RunMode.MOCK,
                    user=UserIdentity(id="mallory", organization="gaia", roles=["user"]),
                    request={"text": "widget-forge"},
                ),
                "temporal-forged-decision",
            )
            run_id = initial.run_id
            waiting = await _wait_for_status(runtime, run_id, RunStatus.WAITING_HUMAN)
            gate_id = waiting.pending_gate_id
            assert gate_id is not None

            # The attack: the Update goes to Temporal directly, never through
            # Gaia's API, so nothing ever authenticated `mallory` as an approver.
            await environment.client.get_workflow_handle(run_id).execute_update(
                "decide",
                {
                    "gate_id": gate_id,
                    "decision": "approved",
                    "decided_by": "mallory",
                    "roles": ["approver"],
                    "comment": "Self-approved straight through the namespace.",
                },
            )
            await environment.client.get_workflow_handle(run_id).result()
            final = await runtime.inspect(run_id)

    assert resources["widget-forge"] == "draft"
    assert final.status == RunStatus.BLOCKED
    assert final.error is not None
    assert final.error.code == ErrorCode.GATE_DECISION_UNVERIFIED

    # And the audit trail says the gate was never authentically approved.
    gate = await runtime.get_gate(gate_id)
    assert gate.status.value == "pending"
    assert gate.decided_by is None
