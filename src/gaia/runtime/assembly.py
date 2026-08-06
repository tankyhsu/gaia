"""Single assembly path for Gaia's selectable execution providers.

`RuntimeAssembler` turns declarative scenario/tool specs into in-process or Temporal Runtime
dependencies. It is the one place in the codebase that wires
specs, guardrail pipelines, budget stores, and the model-provider wrapping
chain together. The FastAPI composition root's `ApiDependencies.from_scenarios`
delegates to it; nothing else should hand-roll a second assembly path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia._authoring.scenario import ScenarioHandler, ScenarioSpec, get_scenario_spec
from gaia.config import GaiaApplicationConfig
from gaia.config.models import PolicyOverrideSettings
from gaia.guardrails import (
    GuardedModelProvider,
    GuardrailPipeline,
    SqlAlchemyGuardrailDecisionStore,
)
from gaia.observability.langfuse import build_langfuse_telemetry
from gaia.observability.model_provider import (
    CompositeModelInvocationSink,
    InstrumentedModelProvider,
    ModelInvocationSink,
)
from gaia.observability.opentelemetry import OpenTelemetryModelInvocationSink
from gaia.observability.store import SqlAlchemyModelInvocationStore
from gaia.observability.tool_store import SqlAlchemyToolInvocationStore
from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.runtime.budget import (
    BudgetedModelProvider,
    InProcessRunBudgetStore,
    TemporalRunBudgetStore,
)
from gaia.runtime.contracts import AuditProjection, RuntimeEngine
from gaia.runtime.dependencies import RuntimeDependencies, ToolRegistry
from gaia.runtime.function_runner import FunctionScenarioRunner
from gaia.runtime.function_tools import function_tool
from gaia.runtime.policy import apply_policy_override
from gaia.runtime.prompt_versions import PromptRunVersionResolver
from gaia.spi.guardrail import ContentGuardrail, GuardrailStage
from gaia.spi.model import ModelProvider
from gaia.spi.prompt import PromptProvider
from gaia.spi.rag import Retriever
from gaia.spi.tool import ToolHandler


def _normalize_guardrails(
    configured: Mapping[GuardrailStage, Iterable[ContentGuardrail]] | None,
    legacy_tool_guardrails: Iterable[ContentGuardrail],
) -> dict[GuardrailStage, tuple[ContentGuardrail, ...]]:
    normalized: dict[GuardrailStage, list[ContentGuardrail]] = {
        stage: [] for stage in GuardrailStage
    }
    for stage, items in (configured or {}).items():
        normalized[GuardrailStage(stage)].extend(items)
    legacy = tuple(legacy_tool_guardrails)
    for stage in (
        GuardrailStage.RETRIEVAL,
        GuardrailStage.TOOL_INPUT,
        GuardrailStage.TOOL_OUTPUT,
    ):
        normalized[stage].extend(legacy)
    return {stage: tuple(items) for stage, items in normalized.items()}


def _scenario_spec_with_override(
    spec: ScenarioSpec,
    override: PolicyOverrideSettings | None,
) -> ScenarioSpec:
    """Return `spec`, or a copy rewritten so its declared policy fields already

    carry the tightened, fingerprinted values, when `override` is configured
    for this scenario.

    This -- rather than wrapping the resulting `FunctionScenarioRunner` in a
    delegating proxy -- is deliberate: `FunctionScenarioRunner.execution_policy`
    and `.version_bundle` are plain derivations of `self._spec`
    (`ScenarioSpec.execution_policy` / `.version_bundle`), and so is the
    `ExecutionPolicy` the runner passes to its own `ScopedToolExecutor` for
    *every* tool call the scenario can reach -- direct `context.tools.call(...)`
    inside the handler just as much as a `ScenarioResponse.propose(...)` side
    effect. A proxy that only intercepts the outer `run`/`execution_policy`
    entry points leaves that internal, self-referential read (`self.execution_policy`
    at `function_runner.py`) pointed at the *original* spec, so `deny_tools`
    would report as enforced (the proxy's `execution_policy` shows it) while a
    direct in-handler tool call sails straight through on the untouched inner
    policy -- fingerprinted, audited evidence of a control that was never
    actually in force. Rewriting the spec before the single
    `FunctionScenarioRunner` is even constructed means there is only ever one
    `ExecutionPolicy` for this scenario, so every path to a tool call, every
    external `runner.execution_policy` read (persistent_engine.py,
    handoff.py, `RuntimeDependencies.__post_init__`), and the
    run's persisted budget row all see the same tightened object -- there is
    no second, stale copy left anywhere to accidentally consult.

    Raises `ValueError` (via `apply_policy_override`, prefixed
    `POLICY_OVERRIDE_INVALID:`) immediately if `override` would loosen the
    policy -- i.e. from `RuntimeAssembler.create_engine`, at application
    startup, never at request time.
    """

    if override is None:
        return spec
    baseline_policy = spec.execution_policy
    updated_policy = apply_policy_override(baseline_policy, override)
    if updated_policy is baseline_policy:
        return spec
    return replace(
        spec,
        policy_version=updated_policy.version,
        allowed_tools=tuple(updated_policy.allowed_tools),
        max_steps=updated_policy.max_steps,
        max_duration_seconds=updated_policy.max_duration_seconds,
        max_model_calls=updated_policy.max_model_calls,
        write_mode=updated_policy.write_mode,
    )


@dataclass(frozen=True)
class RuntimeAssembler:
    """Builds the durable runtime engine from declarative scenario specs.

    This is the single assembly path shared by ApiDependencies.from_scenarios
    and (later) the scenario-runtime starter."""

    config: GaiaApplicationConfig
    scenario_handlers: tuple[ScenarioHandler, ...]
    tool_handlers: tuple[ToolHandler, ...]
    model_provider: ModelProvider | None = None
    retriever: Retriever | Callable[[], Retriever] | None = None
    guardrails: Mapping[GuardrailStage, tuple[ContentGuardrail, ...]] | None = None
    prompt_provider: PromptProvider | Callable[[], PromptProvider] | None = None
    handoff_handlers: Mapping[str, ScenarioHandler] | None = None
    continuation_handlers: Mapping[str, ScenarioHandler] | None = None
    allowed_handoffs: Mapping[str, tuple[str, ...]] | None = None
    max_handoffs: int = 4
    output_correction_attempts: int = 0

    def __post_init__(self) -> None:
        if len(self.tool_handlers) != len({id(handler) for handler in self.tool_handlers}):
            raise ValueError("duplicate tool handler in API dependencies")
        specs = tuple(get_scenario_spec(handler) for handler in self.scenario_handlers)
        scenario_ids = [spec.scenario_id for spec in specs]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("duplicate scenario_id in API dependencies")
        prompt_refs = {
            spec.scenario_id: spec.prompt_ref for spec in specs if spec.prompt_ref is not None
        }
        if prompt_refs and self.prompt_provider is None:
            raise ValueError("scenario PromptRef requires prompt_provider")
        object.__setattr__(self, "guardrails", _normalize_guardrails(self.guardrails, ()))

    def create_engine(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        database_url: str,
    ) -> RuntimeEngine:
        specs = tuple(get_scenario_spec(handler) for handler in self.scenario_handlers)
        tool_registrations = tuple(function_tool(handler) for handler in self.tool_handlers)
        prompt_refs = {
            spec.scenario_id: spec.prompt_ref for spec in specs if spec.prompt_ref is not None
        }
        stage_guardrails = self.guardrails
        assert stage_guardrails is not None  # __post_init__ always normalizes this field
        factory = session_factory

        prompt_provider = self.prompt_provider
        retriever = self.retriever
        runtime_prompt_provider = (
            prompt_provider()
            if callable(prompt_provider) and not isinstance(prompt_provider, PromptProvider)
            else prompt_provider
        )
        runtime_retriever = (
            retriever()
            if callable(retriever) and not isinstance(retriever, Retriever)
            else retriever
        )
        version_resolver = (
            PromptRunVersionResolver(runtime_prompt_provider, prompt_refs)
            if runtime_prompt_provider is not None
            else None
        )
        dependencies_kwargs: dict[str, Any] = {}
        if version_resolver is not None:
            dependencies_kwargs["version_resolver"] = version_resolver
        registry = ToolRegistry(tool_registrations)
        budget_store = (
            InProcessRunBudgetStore()
            if self.config.runtime.execution.provider == "in_process"
            else TemporalRunBudgetStore()
        )
        tool_invocations = SqlAlchemyToolInvocationStore(factory)
        guardrail_sink = SqlAlchemyGuardrailDecisionStore(factory)
        langfuse = build_langfuse_telemetry(
            self.config.observability,
            service_name=self.config.application.name,
            service_version=self.config.application.version,
        )

        def guardrail_pipeline(stage: GuardrailStage) -> GuardrailPipeline | None:
            configured = stage_guardrails[stage]
            return GuardrailPipeline(configured, sink=guardrail_sink) if configured else None

        input_pipeline = guardrail_pipeline(GuardrailStage.INPUT)
        output_pipeline = guardrail_pipeline(GuardrailStage.OUTPUT)
        runtime_model: ModelProvider | None = None
        if self.model_provider is not None:
            model_sinks: list[ModelInvocationSink] = [
                SqlAlchemyModelInvocationStore(factory)
            ]
            if langfuse is not None:
                model_sinks.append(
                    OpenTelemetryModelInvocationSink(
                        langfuse.tracer,
                        langfuse.meter,
                    )
                )
            instrumented_model = InstrumentedModelProvider(
                self.model_provider,
                CompositeModelInvocationSink(model_sinks),
            )
            budgeted_model = BudgetedModelProvider(instrumented_model, budget_store)
            runtime_model = (
                GuardedModelProvider(
                    budgeted_model,
                    input_guardrails=input_pipeline,
                    output_guardrails=output_pipeline,
                    output_correction_attempts=self.output_correction_attempts,
                )
                if (
                    input_pipeline is not None
                    or output_pipeline is not None
                    or self.output_correction_attempts > 0
                )
                else budgeted_model
            )
        retrieval_pipeline = guardrail_pipeline(GuardrailStage.RETRIEVAL)
        tool_input_pipeline = guardrail_pipeline(GuardrailStage.TOOL_INPUT)
        tool_output_pipeline = guardrail_pipeline(GuardrailStage.TOOL_OUTPUT)
        policy_overrides = self.config.runtime.policy_overrides
        # Resolve each scenario's effective (possibly tightened) spec *before*
        # building its runner, so the runner is constructed from -- and only ever
        # knows about -- one final ExecutionPolicy. This raises immediately (i.e.
        # here, inside create_engine, at application startup) for any
        # `runtime.policy_overrides` entry that would loosen a scenario's policy
        # instead of tightening it. See `_scenario_spec_with_override` for why this
        # is done by rewriting the spec rather than wrapping the resulting runner.
        effective_specs = tuple(
            _scenario_spec_with_override(spec, policy_overrides.get(spec.scenario_id))
            for spec in specs
        )
        runners = {
            spec.scenario_id: FunctionScenarioRunner(
                spec.handler,
                spec,
                tools=registry,
                environment=self.config.runtime.environment,
                tool_invocations=tool_invocations,
                model=runtime_model,
                retriever=runtime_retriever,
                input_guardrails=input_pipeline,
                retrieval_guardrails=retrieval_pipeline,
                tool_input_guardrails=tool_input_pipeline,
                tool_output_guardrails=tool_output_pipeline,
                budget=budget_store,
                handoff_handlers=self.handoff_handlers,
                continuation_handlers=self.continuation_handlers,
                # Each runner gets its OWN "scenario" entry from its own spec's
                # allowed_handoffs (declared via `@scenario(allowed_handoffs=...)`);
                # the agent-to-agent routes in `self.allowed_handoffs` (declared via
                # each `@agent_handler(allowed_handoffs=...)`) are shared across every
                # scenario in a multi-scenario application. `self.allowed_handoffs` is
                # unpacked last so a caller that still hand-builds a full routing table
                # (including an explicit "scenario" key, the pre-A6 manual API) keeps
                # taking priority over the spec default.
                allowed_handoffs={
                    "scenario": spec.allowed_handoffs,
                    **(self.allowed_handoffs or {}),
                },
                max_handoffs=self.max_handoffs,
            )
            for spec in effective_specs
        }
        # One projection instance, shared by the selected Runtime writer and the
        # adapter that reads evidence back. In production it outlives Temporal's
        # retention window; in-process development writes the same evidence contract.
        audit_projection = SqlAlchemyAuditProjection(factory)
        runtime_dependencies = RuntimeDependencies(
            runners=runners,
            write_tools=registry,
            tool_input_guardrails=tool_input_pipeline,
            tool_output_guardrails=tool_output_pipeline,
            run_budget_store=budget_store,
            environment=self.config.runtime.environment,
            environment_write_mode=self.config.runtime.effective_write_mode(),
            audit_projection=audit_projection,
            **dependencies_kwargs,
        )
        return self._create_runtime(
            runtime_dependencies,
            audit_projection,
            () if langfuse is None else (langfuse.temporal_interceptor,),
        )

    def _create_runtime(
        self,
        dependencies: RuntimeDependencies,
        audit_projection: AuditProjection,
        temporal_interceptors: tuple[Any, ...],
    ) -> RuntimeEngine:
        """Create the configured lightweight or durable Runtime implementation."""

        if self.config.runtime.execution.provider == "in_process":
            from gaia.runtime.in_process_runtime import InProcessRuntimeEngine

            return InProcessRuntimeEngine(
                dependencies=dependencies,
                audit_projection=audit_projection,
            )

        from gaia.runtime.temporal_backend import TemporalClientBackend
        from gaia.runtime.temporal_runtime import TemporalRuntimeEngine

        return TemporalRuntimeEngine(
            execution=self.config.runtime.execution,
            backend=TemporalClientBackend(
                self.config.runtime.execution,
                interceptors=temporal_interceptors,
            ),
            dependencies=dependencies,
            human_gate_ttl_seconds=self.config.policy.human_gate_ttl_seconds,
            temporal_interceptors=temporal_interceptors,
            audit_projection=audit_projection,
            reason=(
                "Temporal is Gaia's durable execution owner. "
                "Workflow state, recovery, HumanGate messages and retries "
                "belong to Temporal; audit evidence belongs to Gaia."
            ),
        )
