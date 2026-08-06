"""Composition root for the controlled-task application's Temporal Activities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from examples.controlled_task.runner import ControlledTaskRunner
from examples.controlled_task.write_tool import MockResourceWriteAdapter
from gaia.contracts.models import RunMode, WriteMode
from gaia.runtime.contracts import AuditProjection
from gaia.runtime.dependencies import (
    RuntimeDependencies,
    WriteAdapterFactory,
    WriteToolRegistration,
    WriteToolRegistry,
)
from gaia.spi.model import ModelProvider


@dataclass(frozen=True)
class ControlledTaskComposition:
    dependencies: RuntimeDependencies
    runner: ControlledTaskRunner
    resources: dict[str, dict[str, Any]]


def create_controlled_task_composition(
    *,
    resources: dict[str, dict[str, Any]] | None = None,
    workflow: Any | None = None,
    write_adapter_factory: WriteAdapterFactory | None = None,
    environment: RunMode = RunMode.MOCK,
    environment_write_mode: WriteMode = WriteMode.ENABLED,
    model_provider: ModelProvider | None = None,
    audit_projection: AuditProjection | None = None,
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
        audit_projection=audit_projection,
    )
    return ControlledTaskComposition(
        dependencies=dependencies,
        runner=runner,
        resources=runner.resources,
    )
