from pathlib import Path

from gaia import PromptRef, ScenarioContext, scenario
from gaia.contracts.models import RunMode, RunRequest
from gaia.persistence.database import initialize_database
from gaia.runtime import (
    FunctionScenarioRunner,
    PromptRunVersionResolver,
    RuntimeDependencies,
    WriteToolRegistry,
)
from gaia.runtime.engine import RuntimeEngine
from gaia.sdk.prompt import PromptArtifact


class MutablePromptProvider:
    def __init__(self, current: PromptArtifact) -> None:
        self.current = current
        self.resolutions = 0

    async def resolve(self, ref: PromptRef) -> PromptArtifact:
        assert ref.environment == RunMode.MOCK
        self.resolutions += 1
        return self.current


def artifact(version: str, instruction: str) -> PromptArtifact:
    return PromptArtifact(
        prompt_id="hello",
        version=version,
        messages=({"role": "system", "content": instruction},),
    )


async def test_new_runs_pin_current_prompt_but_idempotent_retries_keep_old_version(
    tmp_path: Path,
) -> None:
    prompt_ref = PromptRef(prompt_id="hello", environment=RunMode.MOCK)

    @scenario("hello", prompt=prompt_ref, max_model_calls=0)
    async def hello(context: ScenarioContext) -> dict[str, object]:
        return {"message": context.text}

    provider = MutablePromptProvider(artifact("1.0.0", "First"))
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/gaia.db")
    runtime = RuntimeEngine(
        factory,
        RuntimeDependencies(
            runners={"hello": FunctionScenarioRunner(hello)},
            write_tools=WriteToolRegistry(),
            version_resolver=PromptRunVersionResolver(provider, {"hello": prompt_ref}),
        ),
    )
    request = RunRequest.model_validate(
        {
            "scenario_id": "hello",
            "mode": "mock",
            "user": {
                "id": "developer",
                "organization": "example",
                "roles": ["user"],
            },
            "request": {"text": "Gaia"},
        }
    )

    first = await runtime.create(request, "prompt-pin-first")
    provider.current = artifact("2.0.0", "Second")
    second = await runtime.create(request, "prompt-pin-second")
    repeated = await runtime.create(request, "prompt-pin-first")

    assert first.version_bundle.prompt.startswith("hello:1.0.0@")
    assert second.version_bundle.prompt.startswith("hello:2.0.0@")
    assert repeated.run_id == first.run_id
    assert repeated.version_bundle.prompt == first.version_bundle.prompt
    assert provider.resolutions == 2
