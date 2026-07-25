from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gaia.contracts.models import (
    ExecutionPolicy,
    HumanGateDecisionRequest,
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
)
from gaia.persistence.database import initialize_database
from gaia.runtime import (
    RuntimeDependencies,
    RuntimeOutcome,
    SideEffectProposal,
    WriteToolRegistration,
    WriteToolRegistry,
)
from gaia.runtime.engine import RuntimeEngine
from gaia.runtime.persistent_engine import RuntimePermissionDenied


class FakeRunner:
    def __init__(
        self,
        outcome: RuntimeOutcome | None = None,
        *,
        fail: bool = False,
        fail_bind: bool = False,
        fail_resume: bool = False,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self._outcome = outcome
        self._fail = fail
        self._fail_bind = fail_bind
        self._fail_resume = fail_resume
        self._policy = policy or _policy()
        self.run_count = 0

    @property
    def version_bundle(self) -> VersionBundle:
        return VersionBundle(
            policy="p:1",
            workflow="w:1",
            rules="r:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        )

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return self._policy

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        del run_id, request
        self.run_count += 1
        if self._fail:
            raise RuntimeError("application failed")
        assert self._outcome is not None
        return self._outcome

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        del run_id, gate_id
        if self._fail_bind:
            raise RuntimeError("bind failed")

    def resume(self, *, run_id: str, decision: str) -> None:
        del run_id, decision
        if self._fail_resume:
            raise RuntimeError("resume failed")


class FakeWriteAdapter:
    definition = ToolDefinition(
        name="fake-write",
        version="1",
        kind=ToolKind.WRITE,
        risk_level=RiskLevel.LOW,
        required_roles=[],
        timeout_seconds=1,
        max_retries=0,
        idempotent=True,
    )

    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult:
        del idempotency_key
        return ToolResult(ok=True, status=ToolResultStatus.SUCCEEDED, data=payload)

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None:
        del idempotency_key
        return None


class HighRiskFakeWriteAdapter(FakeWriteAdapter):
    definition = FakeWriteAdapter.definition.model_copy(update={"risk_level": RiskLevel.HIGH})


class SandboxFakeWriteAdapter(FakeWriteAdapter):
    definition = FakeWriteAdapter.definition.model_copy(
        update={"allowed_environments": [RunMode.SANDBOX]}
    )


class CustomerFakeWriteAdapter(FakeWriteAdapter):
    definition = FakeWriteAdapter.definition.model_copy(
        update={"allowed_environments": [RunMode.CUSTOMER]}
    )


class ExplodingFakeWriteAdapter(FakeWriteAdapter):
    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult:
        del payload, idempotency_key
        raise RuntimeError("adapter failed")


def _policy(
    *,
    allowed_tools: list[str] | None = None,
    write_mode: WriteMode = WriteMode.ENABLED,
) -> ExecutionPolicy:
    return ExecutionPolicy(
        policy_id="p",
        version="1",
        scenario_id="fake.application",
        allowed_tools=allowed_tools if allowed_tools is not None else ["fake-write"],
        recognized_roles=["user", "operator"],
        max_steps=10,
        max_duration_seconds=30,
        max_model_calls=1,
        write_mode=write_mode,
        human_gate_rules=[],
    )


def request(
    *,
    mode: RunMode = RunMode.MOCK,
    roles: list[str] | None = None,
) -> RunRequest:
    return RunRequest.model_validate(
        {
            "scenario_id": "fake.application",
            "mode": mode,
            "user": {"id": "user", "organization": "org", "roles": roles or ["user"]},
            "request": {"text": "run"},
        }
    )


async def runtime(
    tmp_path: Path,
    runner: FakeRunner,
    tools: WriteToolRegistry | None = None,
    *,
    environment: RunMode = RunMode.MOCK,
    environment_write_mode: WriteMode = WriteMode.ENABLED,
):
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/runtime.db")
    return RuntimeEngine(
        factory,
        RuntimeDependencies(
            runners={"fake.application": runner},
            write_tools=tools or WriteToolRegistry(),
            environment=environment,
            environment_write_mode=environment_write_mode,
        ),
    )


async def test_application_custom_error_code_is_persisted(tmp_path: Path) -> None:
    engine = await runtime(
        tmp_path,
        FakeRunner(
            RuntimeOutcome(
                status=RunStatus.BLOCKED,
                error_code="DOMAIN_LIMIT_REACHED",
                decision_step="domain_policy",
            )
        ),
    )
    result = await engine.create(request(), "custom-error-key")
    assert result.status == RunStatus.BLOCKED
    assert result.error is not None and result.error.code == "DOMAIN_LIMIT_REACHED"
    events = await engine.events_after(result.run_id)
    assert events[-2].step == "domain_policy"
    assert events[-2].error_code == "DOMAIN_LIMIT_REACHED"


async def test_runner_exception_finishes_run_instead_of_leaving_it_running(tmp_path: Path) -> None:
    engine = await runtime(tmp_path, FakeRunner(fail=True))
    result = await engine.create(request(), "runner-failure-key")
    assert result.status == RunStatus.FAILED
    assert result.error is not None and result.error.code == "INTERNAL_ERROR"
    assert result.error.message == "The application failed while processing the run."
    assert result.error.category == "internal"
    assert result.error.retryable is True
    events = await engine.events_after(result.run_id)
    assert [(event.step, event.status.value) for event in events[-2:]] == [
        ("application_runner", "failed"),
        ("finalize", "succeeded"),
    ]


async def test_low_risk_side_effect_uses_injected_tool_without_gate(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="test",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (WriteToolRegistration(FakeWriteAdapter.definition, lambda _: FakeWriteAdapter()),)
    )
    engine = await runtime(tmp_path, FakeRunner(outcome), tools)
    result = await engine.create(request(), "low-risk-key")
    assert result.status == RunStatus.SUCCEEDED
    assert result.pending_gate_id is None
    assert result.result == {"saved": True}


async def test_application_hook_failures_do_not_lose_approved_command(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="approval required",
            risk_level=RiskLevel.HIGH,
        ),
    )
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                HighRiskFakeWriteAdapter.definition,
                lambda _: HighRiskFakeWriteAdapter(),
            ),
        )
    )
    engine = await runtime(
        tmp_path,
        FakeRunner(outcome, fail_bind=True, fail_resume=True),
        tools,
    )
    waiting = await engine.create(request(), "hook-failure-key")
    assert waiting.status == RunStatus.WAITING_HUMAN
    result = await engine.decide(
        waiting.pending_gate_id or "",
        HumanGateDecisionRequest(
            decision="approved",
            decided_by="approver",
            roles=["approver"],
            comment="approved",
        ),
    )
    assert result.status == RunStatus.SUCCEEDED
    steps = [event.step for event in await engine.events_after(result.run_id)]
    assert "application_bind_gate" in steps
    assert "application_resume" in steps
    assert "execute_side_effect" in steps


async def test_request_mode_cannot_override_server_environment(tmp_path: Path) -> None:
    runner = FakeRunner(RuntimeOutcome(status=RunStatus.SUCCEEDED, result={"ok": True}))
    engine = await runtime(tmp_path, runner)

    with pytest.raises(RuntimePermissionDenied, match="ENVIRONMENT_MODE_MISMATCH"):
        await engine.create(request(mode=RunMode.SANDBOX), "mode-mismatch-key")

    assert runner.run_count == 0


def test_runtime_rejects_adapter_for_a_different_environment() -> None:
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                CustomerFakeWriteAdapter.definition,
                lambda _: CustomerFakeWriteAdapter(),
            ),
        )
    )
    with pytest.raises(ValueError, match="TOOL_ENVIRONMENT_MISMATCH:fake-write"):
        RuntimeDependencies(
            runners={"fake.application": FakeRunner()},
            write_tools=tools,
            environment=RunMode.SANDBOX,
            environment_write_mode=WriteMode.APPROVAL_REQUIRED,
        )


async def test_sandbox_requires_approval_even_for_low_risk_write(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="sandbox write",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                SandboxFakeWriteAdapter.definition,
                lambda _: SandboxFakeWriteAdapter(),
            ),
        )
    )
    engine = await runtime(
        tmp_path,
        FakeRunner(outcome),
        tools,
        environment=RunMode.SANDBOX,
        environment_write_mode=WriteMode.APPROVAL_REQUIRED,
    )

    result = await engine.create(request(mode=RunMode.SANDBOX), "sandbox-approval-key")

    assert result.status == RunStatus.WAITING_HUMAN
    assert result.pending_gate_id


async def test_scenario_policy_can_require_approval_in_mock_environment(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="scenario approval",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (WriteToolRegistration(FakeWriteAdapter.definition, lambda _: FakeWriteAdapter()),)
    )
    engine = await runtime(
        tmp_path,
        FakeRunner(outcome, policy=_policy(write_mode=WriteMode.APPROVAL_REQUIRED)),
        tools,
    )

    result = await engine.create(request(), "scenario-approval-key")

    assert result.status == RunStatus.WAITING_HUMAN


async def test_customer_writes_are_disabled_before_adapter_execution(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="customer write",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                CustomerFakeWriteAdapter.definition,
                lambda _: CustomerFakeWriteAdapter(),
            ),
        )
    )
    engine = await runtime(
        tmp_path,
        FakeRunner(outcome),
        tools,
        environment=RunMode.CUSTOMER,
        environment_write_mode=WriteMode.DISABLED,
    )

    result = await engine.create(request(mode=RunMode.CUSTOMER), "customer-disabled-key")

    assert result.status == RunStatus.BLOCKED
    assert result.error is not None and result.error.code == "WRITE_DISABLED"
    assert result.pending_gate_id is None


async def test_adapter_definition_drift_fails_the_command(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="definition drift",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                FakeWriteAdapter.definition,
                lambda _: HighRiskFakeWriteAdapter(),
            ),
        )
    )
    engine = await runtime(tmp_path, FakeRunner(outcome), tools)

    result = await engine.create(request(), "definition-drift-key")

    assert result.status == RunStatus.FAILED
    assert result.error is not None and result.error.code == "TOOL_DEFINITION_MISMATCH"


async def test_unregistered_tool_is_blocked_before_adapter_creation(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="missing registration",
            risk_level=RiskLevel.LOW,
        ),
    )
    engine = await runtime(tmp_path, FakeRunner(outcome))

    result = await engine.create(request(), "unregistered-tool-key")

    assert result.status == RunStatus.BLOCKED
    assert result.error is not None and result.error.code == "TOOL_NOT_REGISTERED"


async def test_adapter_exception_becomes_auditable_failure(tmp_path: Path) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="adapter exception",
            risk_level=RiskLevel.LOW,
        ),
    )
    tools = WriteToolRegistry(
        (
            WriteToolRegistration(
                ExplodingFakeWriteAdapter.definition,
                lambda _: ExplodingFakeWriteAdapter(),
            ),
        )
    )
    engine = await runtime(tmp_path, FakeRunner(outcome), tools)

    result = await engine.create(request(), "adapter-exception-key")

    assert result.status == RunStatus.FAILED
    assert result.error is not None and result.error.code == "TOOL_ADAPTER_ERROR"


@pytest.mark.parametrize(
    ("definition", "proposal_risk", "roles", "allowed_tools", "expected_code"),
    [
        (
            FakeWriteAdapter.definition.model_copy(update={"required_roles": ["operator"]}),
            RiskLevel.LOW,
            ["user"],
            ["fake-write"],
            "TOOL_ROLE_REQUIRED",
        ),
        (
            FakeWriteAdapter.definition,
            RiskLevel.HIGH,
            ["user"],
            ["fake-write"],
            "TOOL_DEFINITION_MISMATCH",
        ),
        (
            FakeWriteAdapter.definition,
            RiskLevel.LOW,
            ["user"],
            [],
            "TOOL_NOT_ALLOWED",
        ),
    ],
)
async def test_side_effect_policy_violations_block_before_adapter(
    tmp_path: Path,
    definition: ToolDefinition,
    proposal_risk: RiskLevel,
    roles: list[str],
    allowed_tools: list[str],
    expected_code: str,
) -> None:
    outcome = RuntimeOutcome(
        status=RunStatus.RUNNING,
        side_effect=SideEffectProposal(
            step_id="write",
            tool_name="fake-write",
            payload={"saved": True},
            reason="policy check",
            risk_level=proposal_risk,
        ),
    )

    class MatchingAdapter(FakeWriteAdapter):
        pass

    MatchingAdapter.definition = definition
    tools = WriteToolRegistry((WriteToolRegistration(definition, lambda _: MatchingAdapter()),))
    engine = await runtime(
        tmp_path,
        FakeRunner(outcome, policy=_policy(allowed_tools=allowed_tools)),
        tools,
    )

    result = await engine.create(request(roles=roles), f"policy-{expected_code}")

    assert result.status == RunStatus.BLOCKED
    assert result.error is not None and result.error.code == expected_code


def test_runtime_rejects_policy_version_drift() -> None:
    runner = FakeRunner(
        policy=ExecutionPolicy(
            **{
                **_policy().model_dump(),
                "version": "2",
            }
        )
    )

    with pytest.raises(ValueError, match="POLICY_VERSION_MISMATCH:fake.application"):
        RuntimeDependencies(
            runners={"fake.application": runner},
            write_tools=WriteToolRegistry(),
        )
