from __future__ import annotations

import pytest

from gaia import ScenarioContext, ScenarioResponse, get_scenario_spec, scenario
from gaia.contracts.models import RunMode, RunRequest, RunStatus, WriteMode


def request() -> RunRequest:
    return RunRequest.model_validate(
        {
            "scenario_id": "document.review",
            "mode": "mock",
            "user": {
                "id": "developer",
                "organization": "example",
                "roles": ["reviewer"],
            },
            "request": {"text": "review this document"},
        }
    )


async def test_scenario_decorator_keeps_function_and_builds_immutable_contract() -> None:
    async def original(context: ScenarioContext) -> dict[str, object]:
        return {"text": context.text}

    decorated = scenario(
        "document.review",
        version="2.0.0",
        prompt_version="document-review:v3",
        recognized_roles=("reviewer",),
        max_steps=5,
        max_model_calls=2,
    )(original)

    assert decorated is original
    assert await decorated(ScenarioContext(run_id="run-1", request=request())) == {
        "text": "review this document"
    }

    spec = get_scenario_spec(decorated)
    assert spec.scenario_id == "document.review"
    assert spec.execution_policy.recognized_roles == ["reviewer"]
    assert spec.execution_policy.write_mode == WriteMode.DISABLED
    assert spec.version_bundle.workflow == "function:2.0.0"
    assert spec.version_bundle.prompt == "document-review:v3"


def test_scenario_rejects_sync_handlers_and_invalid_metadata() -> None:
    def sync_handler(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(TypeError, match="must be async"):
        scenario("document.review")(sync_handler)  # type: ignore[arg-type]

    async def async_handler(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(ValueError, match="scenario_id"):
        scenario("Document Review")(async_handler)
    with pytest.raises(ValueError, match="recognized_roles"):
        scenario("document.review", recognized_roles=())(async_handler)


def test_scenario_response_rejects_non_terminal_result_without_side_effect() -> None:
    with pytest.raises(ValueError, match="must be terminal"):
        ScenarioResponse(status=RunStatus.RUNNING)


def test_scenario_context_exposes_read_only_request_helpers() -> None:
    context = ScenarioContext(run_id="run-1", request=request())

    assert context.text == "review this document"
    assert context.metadata == {}
    assert context.request.mode == RunMode.MOCK
