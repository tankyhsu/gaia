"""Composition root that injects the controlled-task example into Gaia Runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from examples.controlled_task.runner import ControlledTaskRunner
from examples.controlled_task.write_tool import MockResourceWriteAdapter
from gaia.contracts.models import RunMode, WriteMode
from gaia.runtime.dependencies import (
    RuntimeDependencies,
    WriteAdapterFactory,
    WriteToolRegistration,
    WriteToolRegistry,
)
from gaia.runtime.persistent_engine import PersistentRuntimeEngine
from gaia.sdk.model import ModelProvider


@dataclass(frozen=True)
class ControlledTaskComposition:
    dependencies: RuntimeDependencies
    runner: ControlledTaskRunner
    resources: dict[str, dict[str, Any]]

    def create_runtime(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> PersistentRuntimeEngine:
        return PersistentRuntimeEngine(session_factory, self.dependencies)


def create_controlled_task_composition(
    *,
    resources: dict[str, dict[str, Any]] | None = None,
    workflow: Any | None = None,
    write_adapter_factory: WriteAdapterFactory | None = None,
    environment: RunMode = RunMode.MOCK,
    environment_write_mode: WriteMode = WriteMode.ENABLED,
    model_provider: ModelProvider | None = None,
) -> ControlledTaskComposition:
    runner = ControlledTaskRunner(
        resources=resources,
        workflow=workflow,
        model_provider=model_provider,
    )

    def default_factory(payload: Mapping[str, Any]) -> MockResourceWriteAdapter:
        return MockResourceWriteAdapter(
            runner.resources,
            str(payload.get("write_adapter_mode", "normal")),
        )

    dependencies = RuntimeDependencies(
        runners={"controlled-task": runner},
        write_tools=WriteToolRegistry(
            (
                WriteToolRegistration(
                    MockResourceWriteAdapter.definition,
                    write_adapter_factory or default_factory,
                ),
            )
        ),
        environment=environment,
        environment_write_mode=environment_write_mode,
    )
    return ControlledTaskComposition(
        dependencies=dependencies,
        runner=runner,
        resources=runner.resources,
    )
