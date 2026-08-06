from typing import Any

import pytest

from gaia.contracts.models import RiskLevel, RunStatus, ToolDefinition, ToolKind
from gaia.runtime import (
    ReadToolRegistration,
    RuntimeOutcome,
    SideEffectProposal,
    ToolRegistry,
    WriteToolRegistry,
)


def test_runtime_outcome_rejects_ambiguous_shapes() -> None:
    with pytest.raises(ValueError):
        RuntimeOutcome(status=RunStatus.RUNNING)
    with pytest.raises(ValueError):
        RuntimeOutcome(
            status=RunStatus.SUCCEEDED,
            side_effect=SideEffectProposal(
                step_id="write",
                tool_name="writer",
                payload={},
                reason="test",
                risk_level=RiskLevel.LOW,
            ),
        )


def test_write_tool_registry_is_explicit_and_rejects_duplicates() -> None:
    registry = WriteToolRegistry()

    def factory(payload: Any) -> Any:
        return payload

    definition = ToolDefinition(
        name="writer",
        version="1",
        kind=ToolKind.WRITE,
        risk_level=RiskLevel.LOW,
        required_roles=[],
        timeout_seconds=1,
        max_retries=0,
        idempotent=True,
    )
    registry.register(definition, factory)
    assert registry.names == ("writer",)
    assert registry.definition("writer") == definition
    with pytest.raises(ValueError):
        registry.register(definition, factory)
    with pytest.raises(KeyError):
        registry.create("missing", {})


def test_tool_registry_keeps_read_and_write_names_in_one_namespace() -> None:
    class Reader:
        definition = ToolDefinition(
            name="reader",
            version="1",
            kind=ToolKind.READ,
            risk_level=RiskLevel.LOW,
            required_roles=[],
            timeout_seconds=1,
            max_retries=0,
            idempotent=True,
        )

        async def execute(self, payload: dict[str, Any]) -> Any:
            return payload

    reader = Reader()
    registry = ToolRegistry((ReadToolRegistration(reader.definition, reader),))

    assert registry.names == ("reader",)
    assert registry.read("reader") is reader
    with pytest.raises(ValueError, match="already registered"):
        registry.register_read(reader.definition, reader)
