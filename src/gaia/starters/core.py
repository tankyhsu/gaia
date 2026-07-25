"""Starter descriptors and explicit auto-configuration conditions."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from gaia.components.core import ComponentRegistry
from gaia.config.models import GaiaApplicationConfig


@dataclass(frozen=True)
class StarterDescriptor:
    starter_id: str
    version: str
    capabilities: tuple[str, ...]


class AutoConfigurationCondition(Protocol):
    def match(
        self, config: GaiaApplicationConfig, registry: ComponentRegistry
    ) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class OnProperty:
    path: str
    equals: object

    def match(self, config: GaiaApplicationConfig, registry: ComponentRegistry) -> tuple[bool, str]:
        value: object = config
        for item in self.path.split("."):
            value = getattr(value, item)
        return value == self.equals, f"{self.path}={value!r}"


@dataclass(frozen=True)
class OnProfile:
    name: str

    def match(self, config: GaiaApplicationConfig, registry: ComponentRegistry) -> tuple[bool, str]:
        return config.profile == self.name, f"profile={config.profile}"


@dataclass(frozen=True)
class OnImportAvailable:
    import_path: str

    def match(self, config: GaiaApplicationConfig, registry: ComponentRegistry) -> tuple[bool, str]:
        return importlib.util.find_spec(self.import_path) is not None, self.import_path


@dataclass(frozen=True)
class OnComponent:
    component_id: str

    def match(self, config: GaiaApplicationConfig, registry: ComponentRegistry) -> tuple[bool, str]:
        found = any(item.component_id == self.component_id for item in registry.descriptors())
        return found, self.component_id


@dataclass(frozen=True)
class OnMissingComponent:
    component_id: str

    def match(self, config: GaiaApplicationConfig, registry: ComponentRegistry) -> tuple[bool, str]:
        found = any(item.component_id == self.component_id for item in registry.descriptors())
        return not found, self.component_id


@runtime_checkable
class GaiaStarter(Protocol):
    @property
    def descriptor(self) -> StarterDescriptor: ...

    def defaults(self) -> dict[str, object]: ...
    def conditions(self) -> list[AutoConfigurationCondition]: ...
    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None: ...


@dataclass(frozen=True)
class ConditionReport:
    starter_id: str
    matched: bool
    reasons: tuple[str, ...]


def evaluate_conditions(
    starter: GaiaStarter, config: GaiaApplicationConfig, registry: ComponentRegistry
) -> ConditionReport:
    outcomes = [condition.match(config, registry) for condition in starter.conditions()]
    return ConditionReport(
        starter.descriptor.starter_id,
        all(item[0] for item in outcomes),
        tuple(item[1] for item in outcomes),
    )
