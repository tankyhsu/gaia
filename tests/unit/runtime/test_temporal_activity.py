from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from temporalio.exceptions import ApplicationError

import gaia.runtime.temporal_activity as temporal_activity
from gaia.contracts.models import (
    ExecutionPolicy,
    RiskLevel,
    RunMode,
    RunRequest,
    RunStatus,
    ToolDefinition,
    ToolKind,
    ToolResult,
    ToolResultStatus,
    VersionBundle,
    WriteMode,
    WriteRecoveryStrategy,
)
from gaia.runtime.dependencies import (
    RuntimeContinuation,
    RuntimeDependencies,
    RuntimeHandoff,
    RuntimeOutcome,
    SideEffectProposal,
    ToolRegistry,
)
from gaia.runtime.temporal_activity import TemporalRuntimeActivities
from gaia.testing import InMemoryAuditProjection


class FakeRunner:
    def __init__(
        self,
        outcome: RuntimeOutcome,
        continuation_outcome: RuntimeOutcome | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self._outcome = outcome
        self._continuation_outcome = continuation_outcome
        self._policy = policy
        self.continuation: RuntimeContinuation | None = None

    @property
    def version_bundle(self) -> VersionBundle:
        return VersionBundle(
            policy="p:1",
            workflow="workflow:1",
            rules="rules:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        )

    @property
    def execution_policy(self) -> ExecutionPolicy:
        if self._policy is not None:
            return self._policy
        has_side_effect = self._outcome.side_effect is not None
        return ExecutionPolicy(
            policy_id="p",
            version="1",
            scenario_id="read-only.scenario",
            allowed_tools=["write-ticket"] if has_side_effect else [],
            recognized_roles=["employee"],
            max_steps=10,
            max_duration_seconds=30,
            max_model_calls=2,
            write_mode=(
                WriteMode.APPROVAL_REQUIRED if has_side_effect else WriteMode.DISABLED
            ),
            human_gate_rules=[],
        )

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        del run_id, request
        return self._outcome

    async def run_handoff(self, **kwargs: Any) -> RuntimeOutcome:
        del kwargs
        return self._outcome

    async def run_continuation(
        self,
        *,
        run_id: str,
        request: RunRequest,
        continuation: RuntimeContinuation,
    ) -> RuntimeOutcome:
        del run_id, request
        self.continuation = continuation
        return self._continuation_outcome or self._outcome

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        del run_id, gate_id

    def resume(self, *, run_id: str, decision: str) -> None:
        del run_id, decision


class FakeWriteAdapter:
    def __init__(
        self,
        definition: ToolDefinition,
        payload: dict[str, Any],
        executions: list[str],
    ) -> None:
        self.definition = definition
        self._payload = payload
        self._executions = executions

    async def execute(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ToolResult:
        assert payload == self._payload
        self._executions.append(idempotency_key)
        return ToolResult(
            ok=True,
            status=ToolResultStatus.SUCCEEDED,
            data={"ticket_id": "T-1"},
        )

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None:
        del idempotency_key
        return None


def _payload() -> dict[str, object]:
    return {
        "run_id": "gaia-run-1",
        "request": {
            "scenario_id": "read-only.scenario",
            "mode": RunMode.MOCK.value,
            "user": {
                "id": "employee-1",
                "organization": "gaia",
                "roles": ["employee"],
            },
            "request": {"text": "Summarize this", "metadata": {}},
        },
    }


def _activities(
    outcome: RuntimeOutcome,
    *,
    executions: list[str] | None = None,
    runner: FakeRunner | None = None,
) -> TemporalRuntimeActivities:
    registry = ToolRegistry()
    if outcome.side_effect is not None:
        definition = ToolDefinition(
            name="write-ticket",
            version="1",
            kind=ToolKind.WRITE,
            risk_level=RiskLevel.LOW,
            required_roles=[],
            timeout_seconds=1,
            max_retries=0,
            idempotent=True,
            recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
        )
        recorded_executions = executions if executions is not None else []
        registry.register(
            definition,
            lambda payload: FakeWriteAdapter(
                definition,
                dict(payload),
                recorded_executions,
            ),
        )
    return TemporalRuntimeActivities(
        RuntimeDependencies(
            runners={"read-only.scenario": runner or FakeRunner(outcome)},
            write_tools=registry,
            audit_projection=InMemoryAuditProjection(),
        )
    )


@pytest.mark.asyncio
async def test_read_only_terminal_runner_becomes_temporal_activity_result() -> None:
    activities = _activities(
        RuntimeOutcome(
            status=RunStatus.SUCCEEDED,
            result={"summary": "done"},
            decision_step="complete_summary",
        )
    )

    result = await activities.run_scenario(_payload())

    assert result["status"] == "succeeded"
    assert result["result"] == {"summary": "done"}
    assert result["decision_step"] == "complete_summary"


@pytest.mark.asyncio
async def test_write_proposal_becomes_approval_required_activity_result() -> None:
    activities = _activities(
        RuntimeOutcome(
            status=RunStatus.RUNNING,
            side_effect=SideEffectProposal(
                step_id="write-1",
                tool_name="write-ticket",
                payload={},
                reason="Create ticket",
                risk_level=RiskLevel.LOW,
                uncertainty_rule_refs=("RULE-UNKNOWN",),
            ),
        )
    )

    result = await activities.run_scenario(_payload())

    assert result["status"] == "running"
    assert result["side_effect"]["tool_name"] == "write-ticket"
    assert result["side_effect"]["requires_approval"] is True
    assert result["side_effect"]["recovery_strategy"] == "idempotent"
    assert result["side_effect"]["timeout_seconds"] == 1
    assert result["side_effect"]["uncertainty_rule_refs"] == ["RULE-UNKNOWN"]


@pytest.mark.asyncio
async def test_unregistered_write_is_blocked_before_command_activity() -> None:
    activities = _activities(
        RuntimeOutcome(
            status=RunStatus.RUNNING,
            side_effect=SideEffectProposal(
                step_id="write-1",
                tool_name="missing-tool",
                payload={},
                reason="Missing registration",
                risk_level=RiskLevel.LOW,
            ),
        )
    )

    result = await activities.run_scenario(_payload())

    assert result["status"] == "blocked"
    assert result["error_code"] == "TOOL_NOT_REGISTERED"


@pytest.mark.asyncio
async def test_disabled_write_is_blocked_before_command_activity() -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write-1",
            tool_name="write-ticket",
            payload={},
            reason="Disabled write",
            risk_level=RiskLevel.LOW,
        ),
    )
    policy = FakeRunner(outcome).execution_policy.model_copy(
        update={"write_mode": WriteMode.DISABLED}
    )
    activities = _activities(outcome, runner=FakeRunner(outcome, policy=policy))

    result = await activities.run_scenario(_payload())

    assert result["status"] == "blocked"
    assert result["error_code"] == "WRITE_DISABLED"


@pytest.mark.asyncio
async def test_adapter_definition_drift_fails_before_write_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write-1",
            tool_name="write-ticket",
            payload={},
            reason="Definition drift",
            risk_level=RiskLevel.LOW,
        ),
    )
    definition = ToolDefinition(
        name="write-ticket",
        version="1",
        kind=ToolKind.WRITE,
        risk_level=RiskLevel.LOW,
        required_roles=[],
        timeout_seconds=1,
        max_retries=0,
        idempotent=True,
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )
    mismatched = definition.model_copy(update={"risk_level": RiskLevel.HIGH})
    registry = ToolRegistry()
    registry.register(
        definition,
        lambda payload: FakeWriteAdapter(mismatched, dict(payload), []),
    )
    activities = TemporalRuntimeActivities(
        RuntimeDependencies(
            runners={"read-only.scenario": FakeRunner(outcome)},
            write_tools=registry,
            audit_projection=InMemoryAuditProjection(),
        )
    )
    monkeypatch.setattr(
        temporal_activity.activity,
        "info",
        lambda: SimpleNamespace(attempt=1),
    )

    with pytest.raises(ApplicationError) as error:
        await activities.execute_command(
            {
                "run_id": "gaia-run-1",
                "scenario_id": "read-only.scenario",
                "command_id": "gaia-run-1:command:write-1",
                "proposal": {
                    "tool_name": "write-ticket",
                    "payload": {},
                },
            }
        )

    assert error.value.type == "GaiaTemporalWriteAdapterInvalid"


@pytest.mark.asyncio
async def test_handoff_becomes_temporal_activity_result() -> None:
    activities = _activities(
        RuntimeOutcome(
            status=RunStatus.RUNNING,
            handoff=RuntimeHandoff(
                current_agent="policy",
                input={"resource_id": "R-1"},
                reason="Check policy",
                shared_state={"requester": "employee-1"},
                handoff_count=1,
                steps=(
                    {
                        "source_agent": "scenario",
                        "target_agent": "policy",
                        "reason": "Check policy",
                    },
                ),
            ),
        )
    )

    result = await activities.run_scenario(_payload())

    assert result["status"] == "running"
    assert result["handoff"] == {
        "current_agent": "policy",
        "input": {"resource_id": "R-1"},
        "reason": "Check policy",
        "shared_state": {"requester": "employee-1"},
        "handoff_count": 1,
        "steps": [
            {
                "source_agent": "scenario",
                "target_agent": "policy",
                "reason": "Check policy",
            }
        ],
    }


@pytest.mark.asyncio
async def test_authorized_write_executes_as_temporal_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions: list[str] = []
    activities = _activities(
        RuntimeOutcome(
            status=RunStatus.RUNNING,
            side_effect=SideEffectProposal(
                step_id="write-1",
                tool_name="write-ticket",
                payload={"title": "Broken"},
                reason="Create ticket",
                risk_level=RiskLevel.LOW,
            ),
        ),
        executions=executions,
    )
    monkeypatch.setattr(
        temporal_activity.activity,
        "info",
        lambda: SimpleNamespace(attempt=1),
    )

    result = await activities.execute_command(
        {
            "run_id": "gaia-run-1",
            "scenario_id": "read-only.scenario",
            "command_id": "gaia-run-1:command:write-1",
            "proposal": {
                "tool_name": "write-ticket",
                "payload": {"title": "Broken"},
            },
        }
    )

    assert result == {
        "ok": True,
        "status": "succeeded",
        "data": {"ticket_id": "T-1"},
        "error_code": None,
        "trace_id": None,
    }
    assert executions == ["gaia-run-1:command:write-1"]


@pytest.mark.asyncio
async def test_write_result_can_resume_runner_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write-1",
            tool_name="write-ticket",
            payload={"title": "Broken"},
            reason="Create ticket",
            risk_level=RiskLevel.LOW,
        ),
        continuation=RuntimeContinuation(
            handler="after-ticket",
            input={"source": "scenario"},
        ),
    )
    runner = FakeRunner(
        initial,
        continuation_outcome=RuntimeOutcome(
            status=RunStatus.SUCCEEDED,
            result={"completed": True},
            decision_step="complete_after_ticket",
        ),
    )
    activities = _activities(initial, runner=runner)
    monkeypatch.setattr(
        temporal_activity.activity,
        "info",
        lambda: SimpleNamespace(attempt=1),
    )

    first = await activities.run_scenario(_payload())
    command = await activities.execute_command(
        {
            "run_id": "gaia-run-1",
            "scenario_id": "read-only.scenario",
            "command_id": "gaia-run-1:command:write-1",
            "proposal": first["side_effect"],
        }
    )
    resumed = await activities.run_scenario(
        {
            **_payload(),
            "continuation": {
                **first["continuation"],
                "action_result": command["data"],
            },
        }
    )

    assert resumed["status"] == "succeeded"
    assert resumed["result"] == {"completed": True}
    assert runner.continuation is not None
    assert runner.continuation.handler == "after-ticket"
    assert runner.continuation.action_result == {"ticket_id": "T-1"}
