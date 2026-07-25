from examples.controlled_task.read_tool import MockResourceReadTool


async def test_mock_read_tool_is_read_only_and_deterministic() -> None:
    tool = MockResourceReadTool()
    result = await tool.execute({"resource_id": "res-001"})
    assert result.ok is True
    assert result.data["status"] == "active"
