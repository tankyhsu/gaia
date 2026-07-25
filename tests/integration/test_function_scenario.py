from __future__ import annotations

from gaia import FunctionScenarioRunner, ScenarioContext, scenario
from gaia.contracts.models import RunRequest, RunStatus
from gaia.persistence.database import initialize_database
from gaia.runtime import RuntimeDependencies, WriteToolRegistry
from gaia.runtime.engine import RuntimeEngine


async def test_function_scenario_runs_through_the_durable_runtime(tmp_path) -> None:
    @scenario(
        "hello",
        recognized_roles=("user",),
        max_model_calls=0,
        prompt_version="none",
    )
    async def hello(context: ScenarioContext) -> dict[str, object]:
        return {
            "message": f"Hello, {context.request.user.id}",
            "request_text": context.text,
        }

    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/gaia.db")
    runtime = RuntimeEngine(
        factory,
        RuntimeDependencies(
            runners={"hello": FunctionScenarioRunner(hello)},
            write_tools=WriteToolRegistry(),
        ),
    )
    request = RunRequest.model_validate(
        {
            "scenario_id": "hello",
            "mode": "mock",
            "user": {
                "id": "Ada",
                "organization": "example",
                "roles": ["user"],
            },
            "request": {"text": "Introduce yourself"},
        }
    )

    result = await runtime.create(request, "function-scenario-key")
    events = await runtime.events_after(result.run_id)

    assert result.status == RunStatus.SUCCEEDED
    assert result.result == {
        "message": "Hello, Ada",
        "request_text": "Introduce yourself",
    }
    assert [event.step for event in events] == [
        "received",
        "validate_request",
        "start_workflow",
        "scenario",
        "finalize",
    ]
