from typing import Any

import pytest

from gaia.contracts.models import RiskLevel, RunStatus, ToolDefinition, ToolKind
from gaia.runtime import RuntimeOutcome, SideEffectProposal, WriteToolRegistry


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
