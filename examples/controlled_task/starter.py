"""Example-owned Starter descriptors for the controlled-task application."""

from __future__ import annotations

from dataclasses import dataclass

from gaia.components import ComponentDescriptor, ComponentKind, ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.starters import OnImportAvailable, StarterDescriptor
from gaia.starters.core import AutoConfigurationCondition

from .composition import create_controlled_task_composition


@dataclass(frozen=True)
class ControlledTaskExampleStarter:
    @property
    def descriptor(self) -> StarterDescriptor:
        return StarterDescriptor(
            starter_id="controlled-task-example",
            version="1.0.0",
            capabilities=("application-runner", "write-tool"),
        )

    def defaults(self) -> dict[str, object]:
        return {}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnImportAvailable("langgraph")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        composition = create_controlled_task_composition()
        registry.register(
            ComponentDescriptor(
                component_id="controlled-task-runner",
                kind=ComponentKind.WORKFLOW,
                implementation="examples.controlled_task.runner.ControlledTaskRunner",
                version="1.0.0",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                reason="example-starter:controlled-task",
            ),
            lambda _components: composition.runner,
        )
        registry.register(
            ComponentDescriptor(
                component_id="controlled-task-write-tools",
                kind=ComponentKind.TOOL,
                implementation="examples.controlled_task.composition.WriteToolRegistry",
                version="1.0.0",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                depends_on=("controlled-task-runner",),
                reason="example-starter:controlled-task",
            ),
            lambda _components: composition.dependencies.write_tools,
        )


STARTER = ControlledTaskExampleStarter()
