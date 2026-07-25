"""Dependency contracts consumed by the generic Gaia Runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from gaia.contracts.models import (
    ActorType,
    ErrorCode,
    ExecutionPolicy,
    RiskLevel,
    RunMode,
    RunRequest,
    RunStatus,
    ToolDefinition,
    VersionBundle,
    WriteMode,
)
from gaia.sdk.tool import WriteAdapter


@dataclass(frozen=True)
class RuntimeTraceStep:
    """A scenario-owned step that Runtime persists in the common event stream."""

    name: str
    actor: ActorType = ActorType.SYSTEM
    source_refs: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SideEffectProposal:
    """A side effect requested by an application runner, but not executed by it."""

    step_id: str
    tool_name: str
    payload: Mapping[str, Any]
    reason: str
    risk_level: RiskLevel
    rule_refs: tuple[str, ...] = ()
    uncertainty_rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeOutcome:
    """The application-specific computation returned to the generic Runtime."""

    status: RunStatus
    result: Mapping[str, Any] | None = None
    error_code: ErrorCode | str | None = None
    trace: tuple[RuntimeTraceStep, ...] = ()
    decision_step: str = "evaluate_outcome"
    decision_rule_refs: tuple[str, ...] = ()
    side_effect: SideEffectProposal | None = None

    def __post_init__(self) -> None:
        terminal = {RunStatus.SUCCEEDED, RunStatus.BLOCKED, RunStatus.DEGRADED, RunStatus.FAILED}
        if self.side_effect is None and self.status not in terminal:
            raise ValueError("an outcome without a side effect must be terminal")
        if self.side_effect is not None and self.status != RunStatus.RUNNING:
            raise ValueError("an outcome with a side effect must use running")


class ScenarioRunner(Protocol):
    """Application-owned computation invoked by Runtime for one scenario id."""

    @property
    def version_bundle(self) -> VersionBundle: ...

    @property
    def execution_policy(self) -> ExecutionPolicy: ...

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome: ...

    def bind_gate(self, *, run_id: str, gate_id: str) -> None: ...

    def resume(self, *, run_id: str, decision: str) -> None: ...


class RunVersionResolver(Protocol):
    """Resolve dynamic application assets before a new Run is persisted."""

    async def resolve(
        self,
        request: RunRequest,
        base: VersionBundle,
    ) -> VersionBundle: ...


class VersionResolutionError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class StaticRunVersionResolver:
    async def resolve(self, request: RunRequest, base: VersionBundle) -> VersionBundle:
        del request
        return base


class SideEffectPolicy(Protocol):
    """Application policy deciding whether an admitted side effect needs approval."""

    def requires_approval(self, request: RunRequest, proposal: SideEffectProposal) -> bool: ...


class RiskBasedApprovalPolicy:
    """Default policy: medium and high risk writes require a HumanGate."""

    def requires_approval(self, request: RunRequest, proposal: SideEffectProposal) -> bool:
        del request
        return proposal.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH}


WriteAdapterFactory = Callable[[Mapping[str, Any]], WriteAdapter]


@dataclass(frozen=True)
class WriteToolRegistration:
    definition: ToolDefinition
    factory: WriteAdapterFactory


class WriteToolRegistry:
    """Explicit factories for side-effect adapters, keyed by public tool name."""

    def __init__(self, registrations: Iterable[WriteToolRegistration] = ()) -> None:
        self._registrations: dict[str, WriteToolRegistration] = {}
        for registration in registrations:
            self.register(registration.definition, registration.factory)

    def register(self, definition: ToolDefinition, factory: WriteAdapterFactory) -> None:
        if definition.name in self._registrations:
            raise ValueError(f"write tool already registered: {definition.name}")
        self._registrations[definition.name] = WriteToolRegistration(definition, factory)

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._registrations[name].definition
        except KeyError as error:
            raise KeyError(f"write tool is not registered: {name}") from error

    def create(self, name: str, payload: Mapping[str, Any]) -> WriteAdapter:
        try:
            registration = self._registrations[name]
        except KeyError as error:
            raise KeyError(f"write tool is not registered: {name}") from error
        adapter = registration.factory(payload)
        if adapter.definition != registration.definition:
            raise ValueError("TOOL_DEFINITION_MISMATCH")
        return adapter

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._registrations[name].definition for name in sorted(self._registrations))


@dataclass(frozen=True)
class RuntimeDependencies:
    """All application-specific dependencies required by PersistentRuntimeEngine."""

    runners: Mapping[str, ScenarioRunner]
    write_tools: WriteToolRegistry
    side_effect_policy: SideEffectPolicy = field(default_factory=RiskBasedApprovalPolicy)
    version_resolver: RunVersionResolver = field(default_factory=StaticRunVersionResolver)
    environment: RunMode = RunMode.MOCK
    environment_write_mode: WriteMode = WriteMode.ENABLED

    def __post_init__(self) -> None:
        for scenario_id, runner in self.runners.items():
            if runner.execution_policy.scenario_id != scenario_id:
                raise ValueError(f"POLICY_SCENARIO_MISMATCH:{scenario_id}")
            expected_version = (
                f"{runner.execution_policy.policy_id}:{runner.execution_policy.version}"
            )
            if runner.version_bundle.policy != expected_version:
                raise ValueError(f"POLICY_VERSION_MISMATCH:{scenario_id}")
        for definition in self.write_tools.definitions:
            if self.environment not in definition.allowed_environments:
                raise ValueError(f"TOOL_ENVIRONMENT_MISMATCH:{definition.name}")

    def runner_for(self, scenario_id: str) -> ScenarioRunner:
        try:
            return self.runners[scenario_id]
        except KeyError as error:
            raise KeyError(f"scenario is not registered: {scenario_id}") from error
