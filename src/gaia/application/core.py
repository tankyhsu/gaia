"""GaiaApplication owns component configuration and lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar

from gaia.actuator.models import ActuatorCondition, ActuatorSnapshot
from gaia.components.core import ComponentDescriptor, ComponentRegistry
from gaia.config import ConfigOrigin, GaiaApplicationConfig, ImportedStarterRef, load_config
from gaia.starters import (
    BUILTIN_STARTERS,
    STARTER_DEPENDENCIES,
    AutoConfigurationReport,
    AutoConfigurator,
    GaiaStarter,
    resolve_imported_starter,
)

T = TypeVar("T")


def _framework_version() -> str:
    """Resolve the installed `gaia-framework` package version.

    Falls back to a clearly-marked development sentinel when the package is not
    installed (e.g. running straight from a source checkout without `pip install`/
    `uv sync` having registered distribution metadata) so callers never see a
    version literal that silently drifts from `pyproject.toml`.
    """

    try:
        return version("gaia-framework")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _matches_expected(instance: Any, expected: type) -> bool:
    """Check whether `instance` satisfies the `expected` port type.

    `isinstance()` works directly for concrete classes and for `Protocol`
    subclasses decorated with `@runtime_checkable`. Several SPI ports (for
    example `gaia.spi.model.ModelProvider`) are plain structural `Protocol`s
    without that decorator, so `isinstance()` raises `TypeError` for them. For
    that case we fall back to the same attribute-presence check that
    `@runtime_checkable` itself performs under the hood (it does not verify
    method signatures either): every public attribute declared on the
    protocol must be present on the instance. This gives real verification
    for undecorated ports without requiring every SPI Protocol to add
    `@runtime_checkable` just to be usable as `get_component`'s `expected`.
    """

    try:
        return isinstance(instance, expected)
    except TypeError:
        protocol_attrs = {
            name
            for klass in getattr(expected, "__mro__", (expected,))
            if getattr(klass, "_is_protocol", False)
            for name in vars(klass)
            if not name.startswith("_")
        }
        return all(hasattr(instance, name) for name in protocol_attrs)


class ApplicationState(StrEnum):
    CREATED = "created"
    CONFIGURED = "configured"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class GaiaApplicationContext:
    config: Mapping[str, Any]
    config_hash: str
    components: MappingProxyType[str, Any]
    descriptors: tuple[ComponentDescriptor, ...]
    framework_version: str
    application_version: str
    started_at: datetime | None
    origins: Mapping[str, ConfigOrigin]
    auto_configuration_report: AutoConfigurationReport | None
    component_graph_hash: str


class GaiaApplication:
    def __init__(
        self,
        config: GaiaApplicationConfig,
        registry: ComponentRegistry | None = None,
        origins: Mapping[str, ConfigOrigin] | None = None,
        starters: Mapping[str, GaiaStarter] | None = None,
        starter_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or ComponentRegistry()
        self.state = ApplicationState.CREATED
        self._context: GaiaApplicationContext | None = None
        self._resources: AsyncExitStack | None = None
        self._origins = origins or {}
        self._report: AutoConfigurationReport | None = None
        self._starters = dict(BUILTIN_STARTERS if starters is None else starters)
        self._starter_ids: tuple[str, ...] | None
        if starter_ids is None and all(isinstance(reference, str) for reference in config.starters):
            self._starter_ids = tuple(
                reference
                for reference in _expand_starter_references(config.starters)
                if isinstance(reference, str)
            )
        else:
            self._starter_ids = starter_ids

    @classmethod
    def from_config(cls, path: Path, *, overrides: list[str] | None = None) -> GaiaApplication:
        path = path.expanduser().resolve()
        declared, _, _ = load_config(path, overrides=overrides)
        starters = dict(BUILTIN_STARTERS)
        defaults: dict[str, object] = {}
        resolved_starters: list[str] = []
        for reference in _expand_starter_references(declared.starters):
            starter = (
                resolve_imported_starter(reference)
                if isinstance(reference, ImportedStarterRef)
                else starters.get(reference)
            )
            if starter is None:
                if isinstance(reference, str):
                    resolved_starters.append(reference)
                continue
            starters[starter.descriptor.starter_id] = starter
            resolved_starters.append(starter.descriptor.starter_id)
            defaults = _merge_defaults(defaults, starter.defaults())
        config, origins, _ = load_config(path, overrides=overrides, starter_defaults=defaults)
        config = _resolve_application_paths(config, path.parent)
        return cls(
            config,
            origins=origins,
            starters=starters,
            starter_ids=tuple(resolved_starters),
        )

    async def configure(self) -> GaiaApplicationContext:
        if self._context is not None:
            return self._context
        if self._report is None:
            self.registry, self._report = AutoConfigurator(self._starters).configure(
                self.config,
                self.registry,
                starter_ids=self._starter_ids,
            )
        self.registry.validate()
        descriptors = self.registry.descriptors()
        self._context = GaiaApplicationContext(
            config=_freeze(self.config.redacted()),
            config_hash=self.config.stable_hash(),
            components=MappingProxyType({}),
            descriptors=descriptors,
            framework_version=_framework_version(),
            application_version=self.config.application.version,
            started_at=None,
            origins=MappingProxyType(dict(self._origins)),
            auto_configuration_report=self._report,
            component_graph_hash=_component_graph_hash(descriptors),
        )
        self.state = ApplicationState.CONFIGURED
        return self._context

    async def start(self) -> GaiaApplicationContext:
        if self.state == ApplicationState.STARTED:
            return await self.configure()
        if self.state in {ApplicationState.FAILED, ApplicationState.STOPPED}:
            raise RuntimeError("failed application cannot restart")
        context = await self.configure()
        self.state = ApplicationState.STARTING
        resources = AsyncExitStack()
        try:
            await resources.__aenter__()
            instances = await self.registry.open(resources)
        except Exception:
            self.state = ApplicationState.FAILED
            await resources.aclose()
            raise
        self._resources = resources
        self.state = ApplicationState.STARTED
        self._context = GaiaApplicationContext(
            **{
                **context.__dict__,
                "components": MappingProxyType(instances),
                "started_at": datetime.now(UTC),
            }
        )
        return self._context

    async def stop(self) -> None:
        if self.state in {ApplicationState.STOPPED, ApplicationState.CREATED}:
            self.state = ApplicationState.STOPPED
            return
        self.state = ApplicationState.STOPPING
        try:
            if self._resources is not None:
                await self._resources.aclose()
        finally:
            self._resources = None
            if self._context is not None:
                self._context = GaiaApplicationContext(
                    **{**self._context.__dict__, "components": MappingProxyType({})}
                )
            self.state = ApplicationState.STOPPED

    def get_component(self, component_id: str, expected: type[T] | None = None) -> Any:
        """Look up a started component by id.

        Pass `expected` to assert the port a caller genuinely requires; a component
        registered under `component_id` that does not satisfy `expected` raises a
        `TypeError` carrying the `COMPONENT_TYPE_MISMATCH` code instead of handing
        back an instance the caller cannot actually use. See `_matches_expected` for
        how structural `Protocol` ports without `@runtime_checkable` are handled.
        """

        if self.state != ApplicationState.STARTED or self._context is None:
            raise RuntimeError("APPLICATION_NOT_STARTED")
        try:
            component = self._context.components[component_id]
        except KeyError as error:
            raise KeyError(f"COMPONENT_NOT_FOUND:{component_id}") from error
        if expected is not None and not _matches_expected(component, expected):
            raise TypeError(
                f"COMPONENT_TYPE_MISMATCH:{component_id} expected "
                f"{expected.__name__}, got {type(component).__name__}"
            )
        return component

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[GaiaApplicationContext]:
        context = await self.start()
        try:
            yield context
        finally:
            await self.stop()

    def actuator_snapshot(self) -> ActuatorSnapshot:
        context = self._context
        if context is None:
            raise RuntimeError("application is not configured")
        report = context.auto_configuration_report
        conditions: tuple[ActuatorCondition, ...] = ()
        if report is not None:
            conditions = tuple(
                ActuatorCondition(
                    starter_id=item.starter_id,
                    matched=item.matched,
                    reasons=item.reasons,
                )
                for item in (*report.positive, *report.negative)
            )
        return ActuatorSnapshot(
            application_name=self.config.application.name,
            application_version=context.application_version,
            framework_version=context.framework_version,
            profile=self.config.profile,
            config_hash=context.config_hash,
            component_graph_hash=context.component_graph_hash,
            components=context.descriptors,
            state=self.state.value,
            started_at=context.started_at,
            config=_thaw(context.config),
            origins={key: str(value) for key, value in context.origins.items()},
            conditions=conditions,
        )


def _merge_defaults(base: Mapping[str, object], overlay: Mapping[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        previous = merged.get(key)
        if isinstance(previous, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_defaults(previous, value)
        else:
            merged[key] = value
    return merged


def _resolve_application_paths(
    config: GaiaApplicationConfig,
    application_root: Path,
) -> GaiaApplicationConfig:
    prompt_root = Path(config.prompt.root).expanduser()
    rag_root = Path(config.rag.root).expanduser()
    if not prompt_root.is_absolute():
        prompt_root = application_root / prompt_root
    if not rag_root.is_absolute():
        rag_root = application_root / rag_root
    return config.model_copy(
        update={
            "prompt": config.prompt.model_copy(update={"root": str(prompt_root.resolve())}),
            "rag": config.rag.model_copy(update={"root": str(rag_root.resolve())}),
        }
    )


def _expand_starter_references(
    references: tuple[str | ImportedStarterRef, ...],
) -> tuple[str | ImportedStarterRef, ...]:
    expanded: list[str | ImportedStarterRef] = []
    included: set[str] = set()
    visiting: set[str] = set()

    def add(reference: str | ImportedStarterRef) -> None:
        if isinstance(reference, ImportedStarterRef):
            expanded.append(reference)
            return
        if reference in included:
            return
        if reference in visiting:
            raise ValueError(f"CONFIG_STARTER_DEPENDENCY_CYCLE:{reference}")
        visiting.add(reference)
        for dependency in STARTER_DEPENDENCIES.get(reference, ()):
            add(dependency)
        visiting.remove(reference)
        included.add(reference)
        expanded.append(reference)

    for reference in references:
        add(reference)
    return tuple(expanded)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _component_graph_hash(descriptors: tuple[ComponentDescriptor, ...]) -> str:
    payload = json.dumps(
        [descriptor.model_dump(mode="json") for descriptor in descriptors],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
