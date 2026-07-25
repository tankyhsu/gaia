from datetime import UTC, datetime, timedelta

import pytest

from gaia.contracts.models import ExecutionPolicy, WriteMode
from gaia.runtime.budget import BudgetExceeded, RunBudget


def test_budget_counts_steps_and_model_calls() -> None:
    policy = ExecutionPolicy(
        policy_id="p",
        version="1",
        scenario_id="controlled-task",
        allowed_tools=[],
        recognized_roles=[],
        max_steps=1,
        max_duration_seconds=1,
        max_model_calls=0,
        write_mode=WriteMode.DISABLED,
        human_gate_rules=[],
    )
    budget = RunBudget(policy, datetime.now(UTC))
    budget.enter_step()
    with pytest.raises(BudgetExceeded):
        budget.enter_step()
    with pytest.raises(BudgetExceeded):
        budget.record_model_call()
    with pytest.raises(BudgetExceeded):
        budget.assert_duration(datetime.now(UTC) + timedelta(seconds=2))
