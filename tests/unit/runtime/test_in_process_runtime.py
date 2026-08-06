from __future__ import annotations

import pytest

from gaia.contracts.models import (
    ErrorCode,
    ExecutionPolicy,
    RunInput,
    RunMode,
    RunRequest,
    RunStatus,
    UserIdentity,
    VersionBundle,
)
from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.runtime.contracts import RuntimeConflict
from gaia.runtime.dependencies import (
    RuntimeDependencies,
    RuntimeOutcome,
    SideEffectProposal,
    ToolRegistry,
)
from gaia.runtime.in_process_runtime import InProcessRuntimeEngine


class _Runner:
    def __init__(self, outcome: RuntimeOutcome) -> None:
        self.outcome = outcome

    @property
    def version_bundle(self) -> VersionBundle:
        return VersionBundle(
            policy="knowledge:1",
            workflow="knowledge:1",
            rules="knowledge:1",
            prompt="knowledge:1",
            model_profile="mock",
            toolset="knowledge:1",
            context_profile="default",
        )

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return ExecutionPolicy(
            policy_id="knowledge",
            version="1",
            scenario_id="knowledge.answer",
            allowed_tools=[],
            recognized_roles=["employee"],
            max_steps=8,
            max_duration_seconds=30,
            max_model_calls=1,
            write_mode="disabled",
            human_gate_rules=[],
        )

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        del run_id, request
        return self.outcome


def _request() -> RunRequest:
    return RunRequest(
        scenario_id="knowledge.answer",
        mode=RunMode.MOCK,
        user=UserIdentity(id="employee-1", organization="gaia", roles=["employee"]),
        request={"text": "What is the leave policy?"},
    )


@pytest.mark.asyncio
async def test_in_process_runtime_persists_terminal_run_and_events() -> None:
    factory = await initialize_database("sqlite+aiosqlite:///:memory:")
    try:
        runner = _Runner(RuntimeOutcome(status=RunStatus.SUCCEEDED, result={"answer": "ok"}))
        projection = SqlAlchemyAuditProjection(factory)
        runtime = InProcessRuntimeEngine(
            dependencies=RuntimeDependencies(
                runners={"knowledge.answer": runner},
                write_tools=ToolRegistry(),
                audit_projection=projection,
            ),
            audit_projection=projection,
        )

        created = await runtime.create(_request(), "knowledge-1")

        assert created.status == RunStatus.SUCCEEDED
        assert created.result == {"answer": "ok"}
        assert (await runtime.inspect(created.run_id)).run_id == created.run_id
        assert [event.step for event in await runtime.events_after(created.run_id)] == [
            "run.created",
            "validate_request",
            "start_local_execution",
            "evaluate_outcome",
        ]
    finally:
        await dispose_session_factory(factory)


@pytest.mark.asyncio
async def test_in_process_runtime_refuses_side_effect_that_needs_durable_orchestration() -> None:
    factory = await initialize_database("sqlite+aiosqlite:///:memory:")
    try:
        runner = _Runner(
            RuntimeOutcome(
                status=RunStatus.RUNNING,
                side_effect=SideEffectProposal(
                    step_id="publish",
                    tool_name="hr.publish",
                    payload={"employee_id": "E-1"},
                    reason="publish account",
                    risk_level="high",
                ),
            )
        )
        projection = SqlAlchemyAuditProjection(factory)
        runtime = InProcessRuntimeEngine(
            dependencies=RuntimeDependencies(
                runners={"knowledge.answer": runner},
                write_tools=ToolRegistry(),
                audit_projection=projection,
            ),
            audit_projection=projection,
        )

        created = await runtime.create(_request(), "knowledge-write")

        assert created.status == RunStatus.BLOCKED
        assert created.error is not None
        assert created.error.code == ErrorCode.DURABLE_EXECUTION_REQUIRED
    finally:
        await dispose_session_factory(factory)


@pytest.mark.asyncio
async def test_in_process_runtime_keeps_idempotency_conflict_semantics() -> None:
    factory = await initialize_database("sqlite+aiosqlite:///:memory:")
    try:
        runner = _Runner(RuntimeOutcome(status=RunStatus.SUCCEEDED, result={"answer": "ok"}))
        projection = SqlAlchemyAuditProjection(factory)
        runtime = InProcessRuntimeEngine(
            dependencies=RuntimeDependencies(
                runners={"knowledge.answer": runner},
                write_tools=ToolRegistry(),
                audit_projection=projection,
            ),
            audit_projection=projection,
        )
        await runtime.create(_request(), "same-key")
        changed = _request().model_copy(update={"request": RunInput(text="different")})

        with pytest.raises(RuntimeConflict, match="IDEMPOTENCY_CONFLICT"):
            await runtime.create(changed, "same-key")
    finally:
        await dispose_session_factory(factory)
