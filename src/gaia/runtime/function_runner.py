"""ScenarioRunner adapter for ordinary async Python functions."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from gaia._authoring.scenario import (
    ScenarioContext,
    ScenarioHandler,
    ScenarioResponse,
    ScenarioSpec,
    get_scenario_spec,
)
from gaia.contracts.models import (
    ErrorCode,
    ExecutionPolicy,
    RunMode,
    RunRequest,
    RunStatus,
    VersionBundle,
)
from gaia.guardrails import GuardrailPipeline, GuardrailViolation
from gaia.runtime.budget import BudgetExceeded, RunBudgetStore
from gaia.runtime.dependencies import (
    RuntimeContinuation,
    RuntimeHandoff,
    RuntimeOutcome,
    RuntimeTraceStep,
    SideEffectProposal,
    ToolRegistry,
)
from gaia.runtime.retrieval import ScopedRetriever
from gaia.runtime.tool_execution import (
    NullToolInvocationSink,
    ScopedToolExecutor,
    ToolExecutionError,
    ToolInvocationSink,
)
from gaia.spi.guardrail import GuardrailContext, GuardrailStage
from gaia.spi.model import ModelProvider
from gaia.spi.rag import Retriever


class FunctionScenarioRunner:
    """Adapt a decorated async function to Gaia's sole runtime SPI."""

    def __init__(
        self,
        handler: ScenarioHandler,
        spec: ScenarioSpec | None = None,
        *,
        tools: ToolRegistry | None = None,
        environment: RunMode = RunMode.MOCK,
        tool_invocations: ToolInvocationSink | None = None,
        model: ModelProvider | None = None,
        retriever: Retriever | None = None,
        input_guardrails: GuardrailPipeline | None = None,
        retrieval_guardrails: GuardrailPipeline | None = None,
        tool_input_guardrails: GuardrailPipeline | None = None,
        tool_output_guardrails: GuardrailPipeline | None = None,
        tool_guardrails: GuardrailPipeline | None = None,
        budget: RunBudgetStore | None = None,
        handoff_handlers: Mapping[str, ScenarioHandler] | None = None,
        continuation_handlers: Mapping[str, ScenarioHandler] | None = None,
        allowed_handoffs: Mapping[str, tuple[str, ...]] | None = None,
        max_handoffs: int = 4,
    ) -> None:
        self._handler = handler
        self._spec = spec or get_scenario_spec(handler)
        self._tools = tools
        self._environment = environment
        self._tool_invocations = tool_invocations or NullToolInvocationSink()
        self._model = model
        self._retriever = retriever
        self._input_guardrails = input_guardrails
        self._retrieval_guardrails = retrieval_guardrails or tool_guardrails
        self._tool_input_guardrails = tool_input_guardrails or tool_guardrails
        self._tool_output_guardrails = tool_output_guardrails or tool_guardrails
        self._budget = budget
        self._handoff_handlers = dict(handoff_handlers or {})
        self._continuation_handlers = dict(continuation_handlers or {})
        self._allowed_handoffs = dict(allowed_handoffs or {})
        self._max_handoffs = max_handoffs
        if self._spec.handler is not handler:
            raise ValueError("scenario spec handler does not match the supplied function")
        if max_handoffs < 0:
            raise ValueError("max_handoffs must be non-negative")
        unknown_sources = set(self._allowed_handoffs).difference(
            {"scenario", *self._handoff_handlers}
        )
        if unknown_sources:
            raise ValueError(f"unknown handoff route sources: {sorted(unknown_sources)}")
        unknown_targets = {
            target
            for targets in self._allowed_handoffs.values()
            for target in targets
            if target not in self._handoff_handlers
        }
        if unknown_targets:
            raise ValueError(f"unknown handoff route targets: {sorted(unknown_targets)}")

    @property
    def version_bundle(self) -> VersionBundle:
        return self._spec.version_bundle

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return self._spec.execution_policy

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        return await self._invoke(
            self._handler,
            run_id=run_id,
            request=request,
            source_agent="scenario",
            handoff=None,
            guard_input=True,
        )

    async def run_handoff(
        self,
        *,
        run_id: str,
        request: RunRequest,
        handoff: RuntimeHandoff,
    ) -> RuntimeOutcome:
        handler = self._handoff_handlers.get(handoff.current_agent)
        if handler is None:
            return RuntimeOutcome(
                status=RunStatus.BLOCKED,
                error_code=ErrorCode.HANDOFF_TARGET_NOT_FOUND,
                decision_step="agent_handoff",
            )
        return await self._invoke(
            handler,
            run_id=run_id,
            request=request,
            source_agent=handoff.current_agent,
            handoff=handoff,
            guard_input=False,
        )

    async def run_continuation(
        self,
        *,
        run_id: str,
        request: RunRequest,
        continuation: RuntimeContinuation,
    ) -> RuntimeOutcome:
        handler = self._continuation_handlers.get(continuation.handler)
        if handler is None:
            return RuntimeOutcome(
                status=RunStatus.BLOCKED,
                error_code=ErrorCode.CONTINUATION_HANDLER_NOT_FOUND,
                decision_step="resume_continuation",
            )
        return await self._invoke(
            handler,
            run_id=run_id,
            request=request,
            source_agent="scenario",
            handoff=None,
            guard_input=False,
            continuation=continuation,
        )

    async def _invoke(
        self,
        handler: ScenarioHandler,
        *,
        run_id: str,
        request: RunRequest,
        source_agent: str,
        handoff: RuntimeHandoff | None,
        guard_input: bool,
        continuation: RuntimeContinuation | None = None,
    ) -> RuntimeOutcome:
        try:
            if self._budget is not None:
                await self._budget.reserve_step(run_id)
            safe_request = await self._safe_request(run_id, request) if guard_input else request
            scoped_tools = (
                None
                if self._tools is None
                else ScopedToolExecutor(
                    registry=self._tools,
                    run_id=run_id,
                    request=safe_request,
                    policy=self.execution_policy,
                    environment=self._environment,
                    sink=self._tool_invocations,
                    input_guardrails=self._tool_input_guardrails,
                    output_guardrails=self._tool_output_guardrails,
                    budget=self._budget,
                )
            )
            value = await handler(
                ScenarioContext(
                    run_id=run_id,
                    request=safe_request,
                    tools=scoped_tools,
                    model=self._model,
                    retriever=(
                        None
                        if self._retriever is None
                        else ScopedRetriever(
                            self._retriever,
                            run_id=run_id,
                            request=safe_request,
                            guardrails=self._retrieval_guardrails,
                        )
                    ),
                    agent_id=None if handoff is None else handoff.current_agent,
                    handoff_input={} if handoff is None else handoff.input,
                    shared_state={} if handoff is None else handoff.shared_state,
                    handoff_count=0 if handoff is None else handoff.handoff_count,
                    continuation_input=(
                        {} if continuation is None else continuation.input
                    ),
                    action_result=(
                        {} if continuation is None else continuation.action_result
                    ),
                )
            )
        except (BudgetExceeded, GuardrailViolation, ToolExecutionError) as error:
            return RuntimeOutcome(
                status=RunStatus.BLOCKED,
                error_code=(
                    ErrorCode.BUDGET_EXCEEDED
                    if isinstance(error, BudgetExceeded)
                    else ErrorCode.MODEL_OUTPUT_INVALID
                    if isinstance(error, GuardrailViolation)
                    and error.code == ErrorCode.MODEL_OUTPUT_INVALID.value
                    else ErrorCode.GUARDRAIL_BLOCKED
                    if isinstance(error, GuardrailViolation)
                    else error.code
                ),
                decision_step=(
                    "enforce_budget"
                    if isinstance(error, BudgetExceeded)
                    else "guardrail"
                    if isinstance(error, GuardrailViolation)
                    else "execute_read_tool"
                ),
            )
        return self._to_outcome(value, source_agent=source_agent, prior=handoff)

    def _to_outcome(
        self,
        value: Mapping[str, object] | BaseModel | ScenarioResponse,
        *,
        source_agent: str,
        prior: RuntimeHandoff | None,
    ) -> RuntimeOutcome:
        if isinstance(value, ScenarioResponse):
            runtime_handoff = None
            if value.agent_handoff is not None:
                target = value.agent_handoff.target_agent
                if target not in self._handoff_handlers:
                    return RuntimeOutcome(
                        status=RunStatus.BLOCKED,
                        error_code=ErrorCode.HANDOFF_TARGET_NOT_FOUND,
                        decision_step="agent_handoff",
                    )
                if target not in self._allowed_handoffs.get(source_agent, ()):
                    return RuntimeOutcome(
                        status=RunStatus.BLOCKED,
                        error_code=ErrorCode.HANDOFF_NOT_ALLOWED,
                        decision_step="agent_handoff",
                    )
                handoff_count = 0 if prior is None else prior.handoff_count
                if handoff_count >= self._max_handoffs:
                    return RuntimeOutcome(
                        status=RunStatus.BLOCKED,
                        error_code=ErrorCode.BUDGET_EXCEEDED,
                        decision_step="agent_handoff",
                    )
                shared_state = {} if prior is None else dict(prior.shared_state)
                shared_state.update(value.agent_handoff.state_updates)
                steps = [] if prior is None else list(prior.steps)
                steps.append(
                    {
                        "source_agent": source_agent,
                        "target_agent": target,
                        "reason": value.agent_handoff.reason,
                    }
                )
                runtime_handoff = RuntimeHandoff(
                    current_agent=target,
                    input=dict(value.agent_handoff.input),
                    reason=value.agent_handoff.reason,
                    shared_state=shared_state,
                    handoff_count=handoff_count + 1,
                    steps=tuple(steps),
                )
            return RuntimeOutcome(
                status=value.status,
                result=dict(value.result) if value.result is not None else None,
                pending_result=(
                    dict(value.pending_result) if value.pending_result is not None else None
                ),
                error_code=value.error_code,
                trace=tuple(
                    RuntimeTraceStep(
                        name=step.name,
                        actor=step.actor,
                        source_refs=step.source_refs,
                        rule_refs=step.rule_refs,
                    )
                    for step in value.trace
                ),
                decision_step=value.decision_step,
                decision_rule_refs=value.decision_rule_refs,
                side_effect=(
                    None
                    if value.side_effect is None
                    else SideEffectProposal(
                        step_id=value.side_effect.step_id,
                        tool_name=value.side_effect.tool_name,
                        payload=value.side_effect.payload,
                        reason=value.side_effect.reason,
                        risk_level=value.side_effect.risk_level,
                        depends_on=value.side_effect.depends_on,
                        approval_view=value.side_effect.approval_view,
                        rule_refs=value.side_effect.rule_refs,
                        uncertainty_rule_refs=value.side_effect.uncertainty_rule_refs,
                    )
                ),
                handoff=runtime_handoff,
                continuation=(
                    None
                    if value.continuation is None
                    else RuntimeContinuation(
                        handler=value.continuation.handler,
                        input=dict(value.continuation.input),
                    )
                ),
            )
        result = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        if not isinstance(result, Mapping):
            raise TypeError(
                "scenario handler must return a mapping, BaseModel, or ScenarioResponse"
            )
        return RuntimeOutcome(
            status=RunStatus.SUCCEEDED,
            result=dict(result),
            decision_step="scenario",
        )

    async def _safe_request(self, run_id: str, request: RunRequest) -> RunRequest:
        if self._input_guardrails is None:
            return request
        safe_text = await self._input_guardrails.evaluate(
            request.request.text,
            GuardrailContext(
                stage=GuardrailStage.INPUT,
                run_id=run_id,
                scenario_id=request.scenario_id,
            ),
        )
        return request.model_copy(
            update={"request": request.request.model_copy(update={"text": safe_text})}
        )

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        del run_id, gate_id

    def resume(self, *, run_id: str, decision: str) -> None:
        del run_id, decision
