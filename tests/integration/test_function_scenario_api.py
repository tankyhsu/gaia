from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gaia import ScenarioContext, scenario
from gaia.api.app import ApiDependencies, create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig


def test_minimal_api_dependencies_serve_decorated_scenarios(tmp_path) -> None:
    @scenario("hello", max_model_calls=0)
    async def hello(context: ScenarioContext) -> dict[str, object]:
        return {"message": f"Hello, {context.text}"}

    config = GaiaApplicationConfig()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=ApiDependencies.from_scenarios(config, hello),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "Idempotency-Key": "minimal-api-test",
            },
            json={
                "scenario_id": "hello",
                "mode": "mock",
                "user": {
                    "id": "developer",
                    "organization": "example",
                    "roles": ["user"],
                },
                "request": {"text": "Gaia"},
            },
        )
        model_health = client.get(
            "/v1/model-profiles/current/health",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        replay = client.post(
            "/v1/evals/replays",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            json={"all": True},
        )

    assert response.status_code == 201
    assert response.json()["result"] == {"message": "Hello, Gaia"}
    assert model_health.status_code == 503
    assert replay.status_code == 503


def test_minimal_api_dependencies_reject_duplicate_scenario_ids() -> None:
    @scenario("duplicate")
    async def first(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    @scenario("duplicate")
    async def second(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(ValueError, match="duplicate scenario_id"):
        ApiDependencies.from_scenarios(GaiaApplicationConfig(), first, second)


def test_prompt_ref_requires_explicit_provider() -> None:
    from gaia import PromptRef
    from gaia.contracts.models import RunMode

    @scenario(
        "prompted",
        prompt=PromptRef(prompt_id="prompted", environment=RunMode.MOCK),
    )
    async def prompted(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(ValueError, match="requires prompt_provider"):
        ApiDependencies.from_scenarios(GaiaApplicationConfig(), prompted)


def test_missing_prompt_release_is_an_actionable_api_error(tmp_path) -> None:
    from gaia import PromptRef
    from gaia.contracts.models import RunMode

    class MissingProvider:
        async def resolve(self, ref: PromptRef):
            raise LookupError(ref.prompt_id)

    @scenario(
        "prompted",
        prompt=PromptRef(prompt_id="prompted", environment=RunMode.MOCK),
        max_model_calls=0,
    )
    async def prompted(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    config = GaiaApplicationConfig()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=ApiDependencies.from_scenarios(
            config,
            prompted,
            prompt_provider=MissingProvider(),
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "Idempotency-Key": "missing-prompt-release",
            },
            json={
                "scenario_id": "prompted",
                "mode": "mock",
                "user": {
                    "id": "developer",
                    "organization": "example",
                    "roles": ["user"],
                },
                "request": {"text": "Gaia"},
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "PROMPT_NOT_AVAILABLE"
    assert "Publish" in response.json()["operator_action"]
