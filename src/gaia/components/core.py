"""Framework component descriptors, registry and dependency ordering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from enum import StrEnum
from graphlib import TopologicalSorter
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComponentKind(StrEnum):
    MODEL = "model"
    EMBEDDING = "embedding"
    WORKFLOW = "workflow"
    CONTEXT = "context"
    TOOL = "tool"
    POLICY = "policy"
    EVALUATION = "evaluation"
    DIAGNOSTICS = "diagnostics"
    PERSISTENCE = "persistence"
    CHECKPOINT = "checkpoint"
    MEMORY = "memory"
    VECTOR = "vector"
    CACHE = "cache"
    RATE_LIMIT = "rate_limit"
    OUTBOX = "outbox"
    EVENT_PUBLISHER = "event_publisher"
    CLIENT = "client"
    PROMPT = "prompt"
    RAG = "rag"


class ComponentStatus(StrEnum):
    CONFIGURED = "configured"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class ComponentScope(StrEnum):
    STATIC = "static"
    APPLICATION = "application"


class ComponentHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: ComponentStatus = ComponentStatus.CONFIGURED
    error_code: str | None = None


class ComponentDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)
    component_id: str
    kind: ComponentKind
    implementation: str
    version: str = "1.0.0"
    starter_id: str
    profile: str
    status: ComponentStatus = ComponentStatus.CONFIGURED
    replaceable: bool = True
    configuration_keys: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    scope: ComponentScope = ComponentScope.STATIC
    reason: str
    health: ComponentHealth = Field(default_factory=ComponentHealth)


ComponentResolver = Mapping[str, Any]
ComponentFactory = Callable[[ComponentResolver], Any]
ComponentResourceFactory = Callable[
    [ComponentResolver],
    AbstractAsyncContextManager[Any],
]


@dataclass(frozen=True)
class ComponentSpec:
    descriptor: ComponentDescriptor
    factory: ComponentFactory | ComponentResourceFactory
    managed_resource: bool


class ComponentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ComponentSpec] = {}

    def register(self, descriptor: ComponentDescriptor, factory: ComponentFactory) -> None:
        if descriptor.scope != ComponentScope.STATIC:
            raise ValueError("CONFIG_COMPONENT_SCOPE_INVALID")
        self._register(ComponentSpec(descriptor, factory, managed_resource=False))

    def register_resource(
        self,
        descriptor: ComponentDescriptor,
        factory: ComponentResourceFactory,
    ) -> None:
        if descriptor.scope != ComponentScope.APPLICATION:
            raise ValueError("CONFIG_COMPONENT_SCOPE_INVALID")
        self._register(ComponentSpec(descriptor, factory, managed_resource=True))

    def _register(self, spec: ComponentSpec) -> None:
        descriptor = spec.descriptor
        if descriptor.component_id in self._specs:
            raise ValueError("CONFIG_COMPONENT_DUPLICATE")
        if descriptor.kind in {
            ComponentKind.MODEL,
            ComponentKind.EMBEDDING,
            ComponentKind.WORKFLOW,
            ComponentKind.POLICY,
            ComponentKind.PERSISTENCE,
            ComponentKind.CHECKPOINT,
            ComponentKind.MEMORY,
            ComponentKind.VECTOR,
            ComponentKind.CACHE,
            ComponentKind.RATE_LIMIT,
            ComponentKind.OUTBOX,
            ComponentKind.EVENT_PUBLISHER,
            ComponentKind.PROMPT,
            ComponentKind.RAG,
        }:
            if any(item.descriptor.kind == descriptor.kind for item in self._specs.values()):
                raise ValueError("CONFIG_COMPONENT_AMBIGUOUS")
        self._specs[descriptor.component_id] = spec

    def descriptors(self) -> tuple[ComponentDescriptor, ...]:
        return tuple(self._specs[key].descriptor for key in sorted(self._specs))

    def validate(self) -> None:
        self._ordered_specs()

    def instantiate(self) -> dict[str, Any]:
        if any(spec.managed_resource for spec in self._specs.values()):
            raise RuntimeError("COMPONENT_RESOURCE_REQUIRES_LIFESPAN")
        return self._instantiate_static()

    def _instantiate_static(self) -> dict[str, Any]:
        instances: dict[str, Any] = {}
        for spec in self._ordered_specs():
            instances[spec.descriptor.component_id] = spec.factory(MappingProxyType(instances))
        return instances

    async def open(self, stack: AsyncExitStack) -> dict[str, Any]:
        instances: dict[str, Any] = {}
        for spec in self._ordered_specs():
            resolved = MappingProxyType(instances)
            if spec.managed_resource:
                manager = spec.factory(resolved)
                instances[spec.descriptor.component_id] = await stack.enter_async_context(manager)
            else:
                instances[spec.descriptor.component_id] = spec.factory(resolved)
        return instances

    def _ordered_specs(self) -> tuple[ComponentSpec, ...]:
        graph: dict[str, set[str]] = {}
        for identifier, spec in self._specs.items():
            missing = set(spec.descriptor.depends_on).difference(self._specs)
            if missing:
                raise ValueError("CONFIG_DEPENDENCY_MISSING")
            graph[identifier] = set(spec.descriptor.depends_on)
        try:
            order = tuple(TopologicalSorter(graph).static_order())
        except Exception as error:
            raise ValueError("CONFIG_DEPENDENCY_CYCLE") from error
        return tuple(self._specs[identifier] for identifier in order)
