from __future__ import annotations

import pytest

from gaia import (
    FunctionReadTool,
    FunctionWriteAdapter,
    get_tool_spec,
    read_tool,
    write_tool,
)
from gaia.contracts.models import RiskLevel, RunMode, ToolKind, WriteRecoveryStrategy


async def test_read_tool_keeps_the_function_and_exposes_an_adapter() -> None:
    async def search_documents(query: str) -> dict[str, object]:
        return {"matches": [query]}

    decorated = read_tool(
        "search-documents",
        allowed_environments=(RunMode.MOCK, RunMode.SANDBOX),
    )(search_documents)
    adapter = FunctionReadTool(decorated)

    assert decorated is search_documents
    assert get_tool_spec(decorated).definition.kind == ToolKind.READ
    assert adapter.definition.allowed_environments == [RunMode.MOCK, RunMode.SANDBOX]
    assert (await adapter.execute({"query": "policy"})).data == {"matches": ["policy"]}


async def test_write_tool_requires_reconciliation_and_pins_authorized_payload() -> None:
    executions: dict[str, dict[str, object]] = {}

    async def reconcile(*, idempotency_key: str) -> dict[str, object] | None:
        return executions.get(idempotency_key)

    @write_tool(
        "set-status",
        risk_level=RiskLevel.HIGH,
        required_roles=("operator",),
        reconcile=reconcile,
    )
    async def set_status(
        resource_id: str,
        status: str,
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        result = {"resource_id": resource_id, "status": status}
        executions[idempotency_key] = result
        return result

    adapter = FunctionWriteAdapter(
        set_status,
        {"resource_id": "document-1", "status": "approved"},
    )
    result = await adapter.execute(
        payload={"resource_id": "document-1", "status": "approved"},
        idempotency_key="command-1",
    )

    assert adapter.definition.kind == ToolKind.WRITE
    assert adapter.definition.required_roles == ["operator"]
    assert result.data == {"resource_id": "document-1", "status": "approved"}
    assert (await adapter.reconcile(idempotency_key="command-1")) == result
    with pytest.raises(ValueError, match="payload changed"):
        await adapter.execute(
            payload={"resource_id": "document-1", "status": "rejected"},
            idempotency_key="command-1",
        )


def test_write_tool_rejects_sync_reconciliation() -> None:
    def reconcile(*, idempotency_key: str) -> None:
        del idempotency_key

    async def handler(*, idempotency_key: str) -> dict[str, object]:
        return {"idempotency_key": idempotency_key}

    with pytest.raises(TypeError, match="reconcile handler must be async"):
        write_tool(
            "write",
            risk_level=RiskLevel.LOW,
            required_roles=(),
            reconcile=reconcile,  # type: ignore[arg-type]
        )(handler)


def test_write_tool_supports_explicit_non_reconcilable_recovery_modes() -> None:
    async def legacy_handler(*, idempotency_key: str) -> dict[str, object]:
        return {"idempotency_key": idempotency_key}

    at_most_once = write_tool(
        "legacy-webhook",
        risk_level=RiskLevel.HIGH,
        required_roles=("operator",),
        recovery_strategy=WriteRecoveryStrategy.AT_MOST_ONCE_MANUAL,
    )(legacy_handler)

    async def idempotent_handler(*, idempotency_key: str) -> dict[str, object]:
        return {"idempotency_key": idempotency_key}

    idempotent = write_tool(
        "idempotent-api",
        risk_level=RiskLevel.MEDIUM,
        required_roles=("operator",),
        recovery_strategy=WriteRecoveryStrategy.IDEMPOTENT,
    )(idempotent_handler)

    assert (
        get_tool_spec(at_most_once).definition.recovery_strategy
        == WriteRecoveryStrategy.AT_MOST_ONCE_MANUAL
    )
    assert get_tool_spec(at_most_once).definition.idempotent is False
    assert get_tool_spec(idempotent).definition.idempotent is True
