"""Budget policy enforcement without a SQL Run execution ledger."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from gaia import ScenarioContext, scenario
from gaia.contracts.models import (
    ErrorCode,
    ModelCapabilities,
    ModelEndpointProfile,
    ModelHealth,
    RunMode,
    RunRequest,
    RunStatus,
    UserIdentity,
)
from gaia.guardrails import GuardedModelProvider
from gaia.runtime.budget import (
    BudgetedModelProvider,
    BudgetExceeded,
    TemporalRunBudgetStore,
)
from gaia.runtime.function_runner import FunctionScenarioRunner
from gaia.spi.model import (
    ModelCallContext,
    ModelMessage,
    ModelResult,
    ModelStreamChunk,
)


class Answer(BaseModel):
    text: str


class CountingModel:
    def __init__(self, *, valid: bool = True) -> None:
        self.calls = 0
        self.valid = valid

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        del profile
        return ModelHealth(healthy=True)

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult:
        del messages, output_schema, timeout_seconds, context
        self.calls += 1
        return ModelResult(
            output={"text": "ok"} if self.valid else {},
            model_id=profile.model_id,
        )

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ):
        del profile, messages, timeout_seconds, context
        self.calls += 1
        yield ModelStreamChunk(delta="ok", model_id="test-model")


def _request(scenario_id: str) -> RunRequest:
    return RunRequest(
        scenario_id=scenario_id,
        mode=RunMode.MOCK,
        user=UserIdentity(
            id="user-1",
            roles=["employee"],
            organization="gaia",
        ),
        request={"text": "run"},
    )


def _profile() -> ModelEndpointProfile:
    return ModelEndpointProfile(
        provider_id="test",
        protocol="mock",
        model_id="test-model",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=True,
            max_context_tokens=None,
        ),
        data_residency="local",
        timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_model_call_budget_blocks_before_second_provider_call() -> None:
    store = TemporalRunBudgetStore()
    model = CountingModel()

    @scenario(
        "budget.model",
        max_steps=2,
        max_model_calls=1,
        recognized_roles=("employee",),
    )
    async def handler(context: ScenarioContext) -> dict[str, str]:
        assert context.model is not None
        call_context = ModelCallContext(
            run_id=context.run_id,
            scenario_id=context.request.scenario_id,
            prompt_version="test",
        )
        for _ in range(2):
            await context.model.generate_structured(
                profile=_profile(),
                messages=[ModelMessage(role="user", content="answer")],
                output_schema=Answer,
                timeout_seconds=1,
                context=call_context,
            )
        return {"status": "unexpected"}

    runner = FunctionScenarioRunner(
        handler,
        model=BudgetedModelProvider(model, store),
        budget=store,
    )
    store.activate("budget-run", runner.execution_policy)

    outcome = await runner.run(
        run_id="budget-run",
        request=_request("budget.model"),
    )

    assert outcome.status == RunStatus.BLOCKED
    assert outcome.error_code == ErrorCode.BUDGET_EXCEEDED
    assert model.calls == 1
    assert store.snapshot()["model_calls_used"] == 1


@pytest.mark.asyncio
async def test_concurrent_model_reservations_do_not_overspend() -> None:
    store = TemporalRunBudgetStore()

    @scenario("budget.concurrent", max_steps=2, max_model_calls=1)
    async def handler(context: ScenarioContext) -> dict[str, str]:
        del context
        return {"status": "ok"}

    runner = FunctionScenarioRunner(handler)
    store.activate("budget-concurrent", runner.execution_policy)

    reservations = await asyncio.gather(
        store.reserve_model_call("budget-concurrent"),
        store.reserve_model_call("budget-concurrent"),
        return_exceptions=True,
    )

    assert sum(value is None for value in reservations) == 1
    assert sum(isinstance(value, BudgetExceeded) for value in reservations) == 1
    assert store.snapshot()["model_calls_used"] == 1


@pytest.mark.asyncio
async def test_output_correction_cannot_bypass_model_call_budget() -> None:
    store = TemporalRunBudgetStore()
    model = CountingModel(valid=False)

    @scenario(
        "budget.correction",
        max_steps=2,
        max_model_calls=1,
        recognized_roles=("employee",),
    )
    async def handler(context: ScenarioContext) -> dict[str, str]:
        assert context.model is not None
        await context.model.generate_structured(
            profile=_profile(),
            messages=[ModelMessage(role="user", content="answer")],
            output_schema=Answer,
            timeout_seconds=1,
            context=ModelCallContext(
                run_id=context.run_id,
                scenario_id=context.request.scenario_id,
                prompt_version="test",
            ),
        )
        return {"status": "unexpected"}

    runner = FunctionScenarioRunner(
        handler,
        model=GuardedModelProvider(
            BudgetedModelProvider(model, store),
            output_correction_attempts=1,
        ),
        budget=store,
    )
    store.activate("budget-correction", runner.execution_policy)

    outcome = await runner.run(
        run_id="budget-correction",
        request=_request("budget.correction"),
    )

    assert outcome.status == RunStatus.BLOCKED
    assert outcome.error_code == ErrorCode.BUDGET_EXCEEDED
    assert model.calls == 1
