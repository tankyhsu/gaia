from __future__ import annotations

from examples.controlled_task.model import DeterministicMockProvider
from examples.controlled_task.models import ControlledTaskIntent
from examples.controlled_task.runner import model_profile
from gaia import (
    Citation,
    GuardrailStage,
    ModelCallContext,
    ModelMessage,
    PatternGuardrail,
    PatternRule,
    RetrievalHit,
    RetrievalRequest,
    ScenarioContext,
    ScenarioResponse,
    read_tool,
    scenario,
    write_tool,
)
from gaia.contracts.models import RiskLevel, RunMode, RunRequest, RunStatus, WriteMode
from gaia.testing import ScenarioTestHarness, TestCase, TestDataset


async def test_harness_runs_read_tools_and_records_write_proposals_without_http() -> None:
    writes = 0

    @read_tool("directory.lookup", required_roles=("employee",))
    async def lookup(employee_id: str) -> dict[str, object]:
        return {"employee_id": employee_id, "department": "Finance"}

    async def reconcile_grant(*, idempotency_key: str):
        del idempotency_key
        return None

    @write_tool(
        "iam.grant-access",
        risk_level=RiskLevel.MEDIUM,
        required_roles=("employee",),
        reconcile=reconcile_grant,
    )
    async def grant_access(employee_id: str, *, idempotency_key: str):
        nonlocal writes
        del idempotency_key
        writes += 1
        return {"employee_id": employee_id, "granted": True}

    @scenario(
        "access.plan",
        allowed_tools=("directory.lookup", "iam.grant-access"),
        recognized_roles=("employee",),
        write_mode=WriteMode.ENABLED,
        max_model_calls=0,
    )
    async def plan(context: ScenarioContext) -> ScenarioResponse:
        nonlocal writes
        assert context.tools is not None
        employee = await context.tools.call(lookup, employee_id=context.text)
        return ScenarioResponse.propose(
            context.tools.propose(
                grant_access,
                step_id="grant",
                payload={"employee_id": employee.data["employee_id"]},
                reason="Grant approved role access.",
            ),
            pending_result={"department": employee.data["department"]},
        )

    request = RunRequest.model_validate(
        {
            "scenario_id": "access.plan",
            "mode": "mock",
            "user": {
                "id": "employee-1",
                "organization": "example",
                "roles": ["employee"],
            },
            "request": {"text": "employee-1"},
        }
    )
    result = await ScenarioTestHarness(plan, tools=(lookup, grant_access)).run(request)

    assert result.outcome.status == RunStatus.RUNNING
    assert result.outcome.pending_result == {"department": "Finance"}
    assert result.outcome.side_effect is not None
    assert result.outcome.side_effect.tool_name == "iam.grant-access"
    assert result.outcome.side_effect.payload == {"employee_id": "employee-1"}
    assert result.tool_invocations[0].tool_name == "directory.lookup"
    assert writes == 0


async def test_harness_composes_read_retrieval_and_model_in_mock_and_sandbox() -> None:
    class RetrieverStub:
        async def retrieve(
            self,
            request: RetrievalRequest,
        ) -> tuple[RetrievalHit, ...]:
            return (
                RetrievalHit(
                    text=f"inspect res-001 for {request.user_id}",
                    score=1.0,
                    citation=Citation(
                        document_id="handbook",
                        document_version="1",
                        source_uri="memory://handbook",
                        chunk_id="handbook:0",
                        content_hash="a" * 64,
                        start_offset=0,
                        end_offset=15,
                        permission_basis="role:employee",
                    ),
                ),
            )

    @read_tool(
        "directory.lookup",
        required_roles=("employee",),
        allowed_environments=(RunMode.MOCK, RunMode.SANDBOX),
    )
    async def lookup(employee_id: str) -> dict[str, object]:
        return {"employee_id": employee_id, "department": "Finance"}

    @scenario(
        "knowledge.compose",
        allowed_tools=("directory.lookup",),
        recognized_roles=("employee",),
        max_model_calls=1,
    )
    async def compose(context: ScenarioContext) -> dict[str, object]:
        assert context.tools is not None
        assert context.retriever is not None
        assert context.model is not None
        employee = await context.tools.call(lookup, employee_id=context.request.user.id)
        hits = await context.retriever.retrieve(
            RetrievalRequest(
                tenant_id=context.request.user.organization,
                corpus_id="handbook",
                query=context.text,
                user_id=context.request.user.id,
                roles=tuple(context.request.user.roles),
            )
        )
        interpreted = await context.model.generate_structured(
            profile=model_profile(),
            messages=[ModelMessage(role="user", content=hits[0].text)],
            output_schema=ControlledTaskIntent,
            timeout_seconds=2,
            context=ModelCallContext(
                run_id=context.run_id,
                scenario_id=context.request.scenario_id,
                prompt_version="test",
            ),
        )
        return {
            "department": employee.data["department"],
            "document_id": hits[0].citation.document_id,
            "operation": interpreted.output["operation"],
        }

    dataset = TestDataset(
        dataset_id="knowledge-compose",
        version="1",
        cases=(
            TestCase(
                case_id="annual-leave",
                input={"text": "What is the policy?"},
            ),
        ),
    )

    def request(mode: RunMode, case: TestCase) -> RunRequest:
        return RunRequest(
            scenario_id="knowledge.compose",
            mode=mode,
            user={
                "id": "employee-1",
                "organization": "example",
                "roles": ["employee"],
            },
            request={"text": str(case.input["text"])},
        )

    harness = ScenarioTestHarness(
        compose,
        tools=(lookup,),
        model=DeterministicMockProvider(),
        retriever=RetrieverStub(),
    )
    case = dataset.cases[0]
    mock = await harness.run(request(RunMode.MOCK, case), run_id="mock-run")
    sandbox = await harness.run(request(RunMode.SANDBOX, case), run_id="sandbox-run")

    assert mock.outcome.result == {
        "department": "Finance",
        "document_id": "handbook",
        "operation": "inspect",
    }
    assert sandbox.outcome.result == mock.outcome.result
    assert mock.tool_invocations[0].tool_name == "directory.lookup"
    assert mock.model_invocations[0].run_id == "mock-run"
    assert sandbox.model_invocations[0].run_id == "sandbox-run"

    blocked_harness = ScenarioTestHarness(
        compose,
        tools=(lookup,),
        model=DeterministicMockProvider(),
        retriever=RetrieverStub(),
        guardrails={
            GuardrailStage.INPUT: (
                PatternGuardrail(
                    "test-input",
                    (PatternRule(pattern="inspect", code="INPUT_BLOCKED"),),
                ),
            )
        },
    )
    blocked = await blocked_harness.run(request(RunMode.MOCK, case), run_id="blocked-run")

    assert blocked.outcome.status == RunStatus.BLOCKED
    assert blocked.outcome.error_code == "GUARDRAIL_BLOCKED"
    assert blocked.model_invocations == ()
