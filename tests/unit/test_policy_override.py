"""Config-driven policy overrides at Gaia's Temporal assembly boundary."""

from __future__ import annotations

from typing import Any

import pytest

from gaia import ScenarioContext, get_scenario_spec, read_tool, scenario
from gaia.config.models import PolicyOverrideSettings
from gaia.contracts.models import (
    ErrorCode,
    ExecutionPolicy,
    RunMode,
    RunRequest,
    RunStatus,
    UserIdentity,
    WriteMode,
)
from gaia.runtime.assembly import _scenario_spec_with_override
from gaia.runtime.dependencies import ToolRegistry
from gaia.runtime.function_runner import FunctionScenarioRunner
from gaia.runtime.function_tools import function_tool
from gaia.runtime.policy import apply_policy_override, stricter_write_mode


def _baseline_policy(**overrides: Any) -> ExecutionPolicy:
    fields: dict[str, Any] = {
        "policy_id": "policy-x",
        "version": "1.0.0",
        "scenario_id": "x",
        "allowed_tools": ["a", "b", "c"],
        "recognized_roles": ["user"],
        "max_steps": 10,
        "max_duration_seconds": 30,
        "max_model_calls": 1,
        "write_mode": WriteMode.ENABLED,
        "human_gate_rules": [],
    }
    fields.update(overrides)
    return ExecutionPolicy(**fields)


def _request(scenario_id: str) -> RunRequest:
    return RunRequest(
        scenario_id=scenario_id,
        mode=RunMode.MOCK,
        user=UserIdentity(id="user-1", organization="gaia", roles=["user"]),
        request={"text": "widget-1"},
    )


def test_stricter_write_mode_rank_table() -> None:
    assert stricter_write_mode(WriteMode.DISABLED, WriteMode.ENABLED) == WriteMode.DISABLED
    assert stricter_write_mode(WriteMode.ENABLED, WriteMode.DISABLED) == WriteMode.DISABLED
    assert (
        stricter_write_mode(WriteMode.ENABLED, WriteMode.APPROVAL_REQUIRED)
        == WriteMode.APPROVAL_REQUIRED
    )
    assert (
        stricter_write_mode(WriteMode.APPROVAL_REQUIRED, WriteMode.APPROVAL_REQUIRED)
        == WriteMode.APPROVAL_REQUIRED
    )


def test_no_override_fields_leaves_policy_unchanged() -> None:
    baseline = _baseline_policy()
    result = apply_policy_override(baseline, PolicyOverrideSettings())
    assert result is baseline
    assert result.version == "1.0.0"


def test_identical_override_is_a_noop() -> None:
    baseline = _baseline_policy()
    result = apply_policy_override(
        baseline,
        PolicyOverrideSettings(
            write_mode=WriteMode.ENABLED,
            max_steps=10,
            max_model_calls=1,
            max_duration_seconds=30,
        ),
    )
    assert result is baseline


def test_write_mode_tightening_is_accepted_and_versioned() -> None:
    baseline = _baseline_policy(write_mode=WriteMode.ENABLED)
    result = apply_policy_override(
        baseline,
        PolicyOverrideSettings(write_mode=WriteMode.APPROVAL_REQUIRED),
    )
    assert result.write_mode == WriteMode.APPROVAL_REQUIRED
    assert result.policy_id == baseline.policy_id
    assert "+ovr." in result.version


def test_write_mode_loosening_is_rejected() -> None:
    baseline = _baseline_policy(write_mode=WriteMode.APPROVAL_REQUIRED)
    with pytest.raises(ValueError, match="POLICY_OVERRIDE_INVALID"):
        apply_policy_override(
            baseline,
            PolicyOverrideSettings(write_mode=WriteMode.ENABLED),
        )


@pytest.mark.parametrize(
    "field_name,tighter,looser",
    [
        ("max_steps", 5, 20),
        ("max_model_calls", 0, 5),
        ("max_duration_seconds", 10, 60),
    ],
)
def test_budget_tightening_is_accepted_and_loosening_is_rejected(
    field_name: str,
    tighter: int,
    looser: int,
) -> None:
    baseline = _baseline_policy()
    tightened = apply_policy_override(
        baseline,
        PolicyOverrideSettings(**{field_name: tighter}),
    )
    assert getattr(tightened, field_name) == tighter
    assert "+ovr." in tightened.version
    with pytest.raises(ValueError, match="POLICY_OVERRIDE_INVALID"):
        apply_policy_override(
            baseline,
            PolicyOverrideSettings(**{field_name: looser}),
        )


def test_deny_tools_removes_only_known_names() -> None:
    baseline = _baseline_policy(allowed_tools=["a", "b", "c"])
    result = apply_policy_override(
        baseline,
        PolicyOverrideSettings(deny_tools=("b", "does-not-exist")),
    )
    assert result.allowed_tools == ["a", "c"]
    assert "+ovr." in result.version


def test_override_digest_is_stable_and_content_addressed() -> None:
    baseline = _baseline_policy()
    first = apply_policy_override(baseline, PolicyOverrideSettings(max_steps=5))
    repeated = apply_policy_override(baseline, PolicyOverrideSettings(max_steps=5))
    different = apply_policy_override(baseline, PolicyOverrideSettings(max_steps=3))
    assert first.version == repeated.version
    assert first.version != different.version
    assert ":" not in first.version.split("+", 1)[1]


def test_scenario_spec_rewrite_rejects_loosening_before_workflow_start() -> None:
    @scenario("policy.loosen", write_mode=WriteMode.DISABLED)
    async def handler(context: ScenarioContext) -> dict[str, str]:
        del context
        return {"status": "unused"}

    with pytest.raises(ValueError, match="POLICY_OVERRIDE_INVALID"):
        _scenario_spec_with_override(
            get_scenario_spec(handler),
            PolicyOverrideSettings(write_mode=WriteMode.ENABLED),
        )


def test_scenario_spec_rewrite_carries_budget_and_version_to_runner() -> None:
    @scenario("policy.budget", max_steps=10, max_model_calls=1)
    async def handler(context: ScenarioContext) -> dict[str, str]:
        del context
        return {"status": "ok"}

    effective = _scenario_spec_with_override(
        get_scenario_spec(handler),
        PolicyOverrideSettings(max_steps=2, max_model_calls=0),
    )
    runner = FunctionScenarioRunner(handler, effective)

    assert runner.execution_policy.max_steps == 2
    assert runner.execution_policy.max_model_calls == 0
    assert runner.version_bundle.policy.endswith(effective.policy_version)
    assert "+ovr." in runner.version_bundle.policy


@pytest.mark.asyncio
async def test_denied_read_tool_is_blocked_inside_function_runner() -> None:
    tool_name = "policy.denied.read"
    scenario_id = "policy.denied.handler"

    @read_tool(tool_name)
    async def read(*, resource_id: str) -> dict[str, str]:
        return {"resource_id": resource_id, "status": "ok"}

    @scenario(scenario_id, allowed_tools=(tool_name,), max_model_calls=0)
    async def handler(context: ScenarioContext) -> dict[str, Any]:
        assert context.tools is not None
        result = await context.tools.call(tool_name, resource_id=context.text)
        return dict(result.data)

    registry = ToolRegistry((function_tool(read),))
    baseline = FunctionScenarioRunner(handler, tools=registry)
    tightened_spec = _scenario_spec_with_override(
        get_scenario_spec(handler),
        PolicyOverrideSettings(deny_tools=(tool_name,)),
    )
    tightened = FunctionScenarioRunner(handler, tightened_spec, tools=registry)

    baseline_outcome = await baseline.run(run_id="baseline", request=_request(scenario_id))
    tightened_outcome = await tightened.run(run_id="tightened", request=_request(scenario_id))

    assert baseline_outcome.status == RunStatus.SUCCEEDED
    assert tightened_outcome.status == RunStatus.BLOCKED
    assert tightened_outcome.error_code == ErrorCode.TOOL_NOT_ALLOWED
