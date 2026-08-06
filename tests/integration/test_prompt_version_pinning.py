"""Prompt release pinning through real Temporal Workflow identity."""

from __future__ import annotations

from uuid import uuid4

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gaia import PromptRef, ScenarioContext, scenario
from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import RunMode, RunRequest, UserIdentity
from gaia.runtime import (
    FunctionScenarioRunner,
    PromptRunVersionResolver,
    RuntimeDependencies,
    WriteToolRegistry,
)
from gaia.runtime.temporal_backend import TemporalClient, TemporalClientBackend
from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.runtime.temporal_worker import gaia_workflow_runner
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow
from gaia.spi.prompt import PromptArtifact
from gaia.testing import InMemoryAuditProjection


class MutablePromptProvider:
    def __init__(self, current: PromptArtifact) -> None:
        self.current = current

    async def resolve(self, ref: PromptRef) -> PromptArtifact:
        assert ref.environment == RunMode.MOCK
        return self.current


def artifact(version: str, instruction: str) -> PromptArtifact:
    return PromptArtifact(
        prompt_id="hello",
        version=version,
        messages=({"role": "system", "content": instruction},),
    )


@pytest.mark.external
@pytest.mark.asyncio
async def test_temporal_workflow_identity_keeps_prompt_version_pinned() -> None:
    prompt_ref = PromptRef(prompt_id="hello", environment=RunMode.MOCK)

    @scenario("hello", prompt=prompt_ref, max_model_calls=0)
    async def hello(context: ScenarioContext) -> dict[str, object]:
        return {"message": context.text}

    provider = MutablePromptProvider(artifact("1.0.0", "First"))
    audit = InMemoryAuditProjection()
    dependencies = RuntimeDependencies(
        runners={"hello": FunctionScenarioRunner(hello)},
        write_tools=WriteToolRegistry(),
        version_resolver=PromptRunVersionResolver(
            provider,
            {"hello": prompt_ref},
        ),
        audit_projection=audit,
    )
    task_queue = f"gaia-prompt-pin-{uuid4()}"
    execution = RuntimeExecutionSettings(task_queue=task_queue)
    request = RunRequest(
        scenario_id="hello",
        mode=RunMode.MOCK,
        user=UserIdentity(
            id="developer",
            organization="example",
            roles=["user"],
        ),
        request={"text": "Gaia"},
    )

    async with await WorkflowEnvironment.start_local(
        search_attributes=(
            GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
            GAIA_SCENARIO_SEARCH_ATTRIBUTE,
            GAIA_STATUS_SEARCH_ATTRIBUTE,
        )
    ) as environment:

        async def client_factory() -> TemporalClient:
            return environment.client

        runtime = TemporalRuntimeEngine(
            execution=execution,
            backend=TemporalClientBackend(
                execution,
                client_factory=client_factory,
            ),
            dependencies=dependencies,
            audit_projection=audit,
        )
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflow_runner=gaia_workflow_runner(),
            workflows=(GaiaRuntimeWorkflow,),
            activities=runtime.activity_handlers(),
        ):
            first = await runtime.create(request, "prompt-pin-first")
            await environment.client.get_workflow_handle(first.run_id).result()
            first = await runtime.inspect(first.run_id)

            provider.current = artifact("2.0.0", "Second")
            second = await runtime.create(request, "prompt-pin-second")
            await environment.client.get_workflow_handle(second.run_id).result()
            second = await runtime.inspect(second.run_id)

            repeated = await runtime.create(request, "prompt-pin-first")

    assert first.version_bundle.prompt.startswith("hello:1.0.0@")
    assert second.version_bundle.prompt.startswith("hello:2.0.0@")
    assert repeated.run_id == first.run_id
    assert repeated.version_bundle.prompt == first.version_bundle.prompt
