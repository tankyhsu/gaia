from __future__ import annotations

from gaia import (
    FunctionScenarioRunner,
    ScenarioContext,
    ScenarioResponse,
    ScenarioSideEffect,
    function_write_tool,
    scenario,
    write_tool,
)
from gaia.contracts.models import (
    Decision,
    HumanGateDecisionRequest,
    RiskLevel,
    RunRequest,
    RunStatus,
    WriteMode,
)
from gaia.persistence.database import initialize_database
from gaia.runtime import RuntimeDependencies, WriteToolRegistry
from gaia.runtime.engine import RuntimeEngine


async def test_function_write_tool_keeps_human_gate_and_idempotency_boundary(
    tmp_path,
) -> None:
    resources = {"document-1": "draft"}
    executions: dict[str, dict[str, object]] = {}

    async def reconcile(*, idempotency_key: str) -> dict[str, object] | None:
        return executions.get(idempotency_key)

    @write_tool(
        "approve-document",
        risk_level=RiskLevel.HIGH,
        required_roles=("operator",),
        reconcile=reconcile,
    )
    async def approve_document(
        document_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        resources[document_id] = "approved"
        result = {"document_id": document_id, "status": "approved"}
        executions[idempotency_key] = result
        return result

    @scenario(
        "document.approval",
        allowed_tools=("approve-document",),
        recognized_roles=("operator",),
        write_mode=WriteMode.ENABLED,
        max_model_calls=0,
    )
    async def approve(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.propose(
            ScenarioSideEffect(
                step_id="approve",
                tool_name="approve-document",
                payload={"document_id": context.text},
                reason="Approval changes a durable business record.",
                risk_level=RiskLevel.HIGH,
            )
        )

    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/gaia.db")
    runtime = RuntimeEngine(
        factory,
        RuntimeDependencies(
            runners={"document.approval": FunctionScenarioRunner(approve)},
            write_tools=WriteToolRegistry((function_write_tool(approve_document),)),
        ),
    )
    request = RunRequest.model_validate(
        {
            "scenario_id": "document.approval",
            "mode": "mock",
            "user": {
                "id": "operator-1",
                "organization": "example",
                "roles": ["operator"],
            },
            "request": {"text": "document-1"},
        }
    )

    waiting = await runtime.create(request, "function-write-key")
    assert waiting.status == RunStatus.WAITING_HUMAN
    assert resources["document-1"] == "draft"

    completed = await runtime.decide(
        waiting.pending_gate_id or "",
        HumanGateDecisionRequest(
            decision=Decision.APPROVED,
            decided_by="approver-1",
            roles=["approver"],
            comment="Approved for the integration test.",
        ),
    )
    repeated = await runtime.create(request, "function-write-key")

    assert completed.status == RunStatus.SUCCEEDED
    assert completed.result == {"document_id": "document-1", "status": "approved"}
    assert resources["document-1"] == "approved"
    assert repeated.run_id == completed.run_id
    assert len(executions) == 1
