"""Dependency contracts consumed by the generic Gaia Runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from gaia.contracts.models import (
    ActorType,
    ApprovalView,
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
from gaia.guardrails import GuardrailPipeline
from gaia.runtime.budget import RunBudgetStore
from gaia.runtime.contracts import AuditProjection
from gaia.spi.tool import ReadTool, WriteAdapter


@dataclass(frozen=True)
class RuntimeTraceStep:
    """A scenario-owned step that Runtime persists in the common event stream."""

    name: str
    actor: ActorType = ActorType.SYSTEM
    source_refs: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeHandoff:
    current_agent: str
    input: Mapping[str, Any]
    reason: str
    shared_state: Mapping[str, Any]
    handoff_count: int
    steps: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RuntimeContinuation:
    handler: str
    input: Mapping[str, Any]
    action_result: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SideEffectProposal:
    """A side effect requested by an application runner, but not executed by it."""

    step_id: str
    tool_name: str
    payload: Mapping[str, Any]
    reason: str
    risk_level: RiskLevel
    depends_on: tuple[str, ...] = ()
    approval_view: ApprovalView | None = None
    rule_refs: tuple[str, ...] = ()
    uncertainty_rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeOutcome:
    """The application-specific computation returned to the generic Runtime."""

    status: RunStatus
    result: Mapping[str, Any] | None = None
    pending_result: Mapping[str, Any] | None = None
    error_code: ErrorCode | str | None = None
    trace: tuple[RuntimeTraceStep, ...] = ()
    decision_step: str = "evaluate_outcome"
    decision_rule_refs: tuple[str, ...] = ()
    side_effect: SideEffectProposal | None = None
    handoff: RuntimeHandoff | None = None
    continuation: RuntimeContinuation | None = None

    def __post_init__(self) -> None:
        terminal = {RunStatus.SUCCEEDED, RunStatus.BLOCKED, RunStatus.DEGRADED, RunStatus.FAILED}
        continuations = sum((self.side_effect is not None, self.handoff is not None))
        if continuations > 1:
            raise ValueError("use one Runtime continuation")
        if continuations == 0 and self.status not in terminal:
            raise ValueError("an outcome without continuation must be terminal")
        if continuations > 0 and self.status != RunStatus.RUNNING:
            raise ValueError("an outcome with continuation must use running")
        if self.pending_result is not None and continuations == 0:
            raise ValueError("pending_result requires a continuation")
        if self.continuation is not None and self.side_effect is None:
            raise ValueError("post-action continuation requires a side effect")


class ScenarioRunner(Protocol):
    """Application-owned computation invoked by Runtime for one scenario id."""

    @property
    def version_bundle(self) -> VersionBundle: ...

    @property
    def execution_policy(self) -> ExecutionPolicy: ...

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome: ...

    async def run_handoff(
        self,
        *,
        run_id: str,
        request: RunRequest,
        handoff: RuntimeHandoff,
    ) -> RuntimeOutcome: ...

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


@dataclass(frozen=True)
class ReadToolRegistration:
    definition: ToolDefinition
    adapter: ReadTool


class ToolRegistry:
    """Explicit read adapters and write factories, keyed by public tool name."""

    def __init__(
        self,
        registrations: Iterable[WriteToolRegistration | ReadToolRegistration] = (),
    ) -> None:
        self._read: dict[str, ReadToolRegistration] = {}
        self._write: dict[str, WriteToolRegistration] = {}
        for registration in registrations:
            if isinstance(registration, ReadToolRegistration):
                self.register_read(registration.definition, registration.adapter)
            else:
                self.register_write(registration.definition, registration.factory)

    def register(self, definition: ToolDefinition, factory: WriteAdapterFactory) -> None:
        """Compatibility alias for registering a write tool."""

        self.register_write(definition, factory)

    def register_read(self, definition: ToolDefinition, adapter: ReadTool) -> None:
        self._ensure_available(definition.name)
        self._read[definition.name] = ReadToolRegistration(definition, adapter)

    def register_write(self, definition: ToolDefinition, factory: WriteAdapterFactory) -> None:
        self._ensure_available(definition.name)
        self._write[definition.name] = WriteToolRegistration(definition, factory)

    def definition(self, name: str) -> ToolDefinition:
        if name in self._read:
            return self._read[name].definition
        if name in self._write:
            return self._write[name].definition
        raise KeyError(f"tool is not registered: {name}")

    def read(self, name: str) -> ReadTool:
        try:
            return self._read[name].adapter
        except KeyError as error:
            raise KeyError(f"read tool is not registered: {name}") from error

    def create(self, name: str, payload: Mapping[str, Any]) -> WriteAdapter:
        try:
            registration = self._write[name]
        except KeyError as error:
            raise KeyError(f"write tool is not registered: {name}") from error
        adapter = registration.factory(payload)
        if adapter.definition != registration.definition:
            raise ValueError("TOOL_DEFINITION_MISMATCH")
        return adapter

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted((*self._read, *self._write)))

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self.definition(name) for name in self.names)

    @property
    def read_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._read))

    @property
    def write_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._write))

    def _ensure_available(self, name: str) -> None:
        if name in self._read or name in self._write:
            raise ValueError(f"tool already registered: {name}")


class WriteToolRegistry(ToolRegistry):
    """Backward-compatible name for the unified ToolRegistry."""


@dataclass(frozen=True)
class RuntimeDependencies:
    """Application dependencies executed locally or by Gaia's Temporal Activities."""

    runners: Mapping[str, ScenarioRunner]
    write_tools: ToolRegistry
    side_effect_policy: SideEffectPolicy = field(default_factory=RiskBasedApprovalPolicy)
    version_resolver: RunVersionResolver = field(default_factory=StaticRunVersionResolver)
    tool_input_guardrails: GuardrailPipeline | None = None
    tool_output_guardrails: GuardrailPipeline | None = None
    run_budget_store: RunBudgetStore | None = None
    environment: RunMode = RunMode.MOCK
    environment_write_mode: WriteMode = WriteMode.ENABLED
    # Durable evidence store. `None` means the selected Runtime cannot record
    # audit evidence at all. Temporal's `record_audit` Activity and the in-process
    # development Runtime both fail loudly instead of creating an untracked Run.
    audit_projection: AuditProjection | None = None

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
