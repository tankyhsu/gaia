import pytest

from examples.controlled_task.read_tool import DEFAULT_RESOURCES
from examples.controlled_task.write_tool import MockResourceWriteAdapter
from gaia.runtime.side_effects import CommandNotApproved, SideEffectExecutor


async def test_side_effect_cannot_execute_without_approval_and_is_idempotent() -> None:
    resources = {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
    adapter = MockResourceWriteAdapter(resources)
    executor = SideEffectExecutor(adapter)
    with pytest.raises(CommandNotApproved):
        await executor.execute(command_key="key", payload={})
    executor.approve("key")
    payload = {"resource_id": "res-001", "target_status": "paused"}
    await executor.execute(command_key="key", payload=payload)
    await executor.execute(command_key="key", payload=payload)
    assert adapter.success_count == 1


async def test_unknown_write_is_not_retried_without_reconciliation() -> None:
    resources = {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
    executor = SideEffectExecutor(MockResourceWriteAdapter(resources, mode="timeout_unknown"))
    executor.approve("key")
    result = await executor.execute(command_key="key", payload={"resource_id": "res-001"})
    assert result.status.value == "unknown"
