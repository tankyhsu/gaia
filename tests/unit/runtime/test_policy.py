import pytest

from gaia.contracts.models import ExecutionPolicy, WriteMode
from gaia.runtime.policy import PolicyDenied, validate_roles, validate_tool_allowed


@pytest.fixture
def policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        policy_id="p",
        version="1",
        scenario_id="controlled-task",
        allowed_tools=["read"],
        recognized_roles=["reader"],
        max_steps=1,
        max_duration_seconds=1,
        max_model_calls=0,
        write_mode=WriteMode.DISABLED,
        human_gate_rules=[],
    )


def test_policy_rejects_unknown_tools_and_roles(policy: ExecutionPolicy) -> None:
    validate_tool_allowed(policy, "read")
    with pytest.raises(PolicyDenied):
        validate_tool_allowed(policy, "write")
    with pytest.raises(PolicyDenied):
        validate_roles(policy, ["admin"])
