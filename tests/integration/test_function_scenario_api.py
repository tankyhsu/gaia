"""Function Scenario composition contracts for the Temporal-only API path."""

from __future__ import annotations

import pytest

from gaia import PromptRef, ScenarioContext, scenario
from gaia.api.app import ApiDependencies
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import RunMode, RunRequest, UserIdentity
from gaia.persistence.database import (
    dispose_session_factory,
    initialize_database,
)
from gaia.runtime.dependencies import VersionResolutionError
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine


@pytest.mark.asyncio
async def test_scenario_api_dependencies_build_temporal_runtime() -> None:
    @scenario("hello", max_model_calls=0)
    async def hello(context: ScenarioContext) -> dict[str, object]:
        return {"message": f"Hello, {context.text}"}

    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})
    dependencies = ApiDependencies.from_scenarios(config, hello)
    database_url = "sqlite+aiosqlite:///:memory:"
    factory = await initialize_database(database_url)
    try:
        runtime = dependencies.runtime_factory(factory, database_url)
    finally:
        await dispose_session_factory(factory)

    assert isinstance(runtime, TemporalRuntimeEngine)
    assert [handler.__name__ for handler in runtime.activity_handlers()] == [
        "run_scenario",
        "execute_command",
        "record_audit",
    ]


def test_scenario_api_dependencies_reject_duplicate_ids() -> None:
    @scenario("duplicate")
    async def first(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    @scenario("duplicate")
    async def second(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(ValueError, match="duplicate scenario_id"):
        ApiDependencies.from_scenarios(
            GaiaApplicationConfig(),
            first,
            second,
        )


@pytest.mark.asyncio
async def test_missing_prompt_release_fails_before_temporal_workflow_start() -> None:
    class MissingProvider:
        async def resolve(self, ref: PromptRef):
            raise LookupError(ref.prompt_id)

    prompt_ref = PromptRef(prompt_id="prompted", environment=RunMode.MOCK)

    @scenario("prompted", prompt=prompt_ref, max_model_calls=0)
    async def prompted(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})
    dependencies = ApiDependencies.from_scenarios(
        config,
        prompted,
        prompt_provider=MissingProvider(),
    )
    database_url = "sqlite+aiosqlite:///:memory:"
    factory = await initialize_database(database_url)
    try:
        runtime = dependencies.runtime_factory(factory, database_url)
        with pytest.raises(VersionResolutionError) as captured:
            await runtime.create(
                RunRequest(
                    scenario_id="prompted",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="developer",
                        organization="example",
                        roles=["user"],
                    ),
                    request={"text": "Gaia"},
                ),
                "missing-prompt-release",
            )
    finally:
        await dispose_session_factory(factory)

    assert captured.value.code == "PROMPT_NOT_AVAILABLE"
    assert captured.value.retryable is False
