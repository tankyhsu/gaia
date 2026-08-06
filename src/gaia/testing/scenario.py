"""In-process Scenario harness for business-flow tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from gaia._authoring.scenario import ScenarioHandler
from gaia.contracts.models import RunRequest
from gaia.guardrails import GuardedModelProvider, GuardrailPipeline
from gaia.observability import InstrumentedModelProvider, ModelInvocationSink
from gaia.observability.models import ModelInvocation, ToolInvocation
from gaia.runtime import (
    FunctionScenarioRunner,
    RuntimeOutcome,
    ToolRegistry,
    function_tool,
)
from gaia.runtime.tool_execution import ToolInvocationSink
from gaia.spi.guardrail import ContentGuardrail, GuardrailStage
from gaia.spi.model import ModelProvider
from gaia.spi.rag import Retriever
from gaia.spi.tool import ToolHandler


@dataclass
class _InvocationCollector(ToolInvocationSink):
    values: list[ToolInvocation] = field(default_factory=list)

    async def record(self, invocation: ToolInvocation) -> None:
        self.values.append(invocation)


@dataclass
class _ModelCollector(ModelInvocationSink):
    values: list[ModelInvocation] = field(default_factory=list)

    async def record(self, invocation: ModelInvocation) -> None:
        self.values.append(invocation)


@dataclass(frozen=True)
class ScenarioHarnessResult:
    outcome: RuntimeOutcome
    tool_invocations: tuple[ToolInvocation, ...]
    model_invocations: tuple[ModelInvocation, ...] = ()


class ScenarioTestHarness:
    """Run one logical Scenario step with policy checks and in-memory evidence.

    The harness deliberately stops at a ``SideEffectProposal``. Durable execution,
    HumanGate decisions, retries, and recovery belong to Temporal and are covered
    by the real Worker integration suite rather than reimplemented in the test harness.
    """

    def __init__(
        self,
        handler: ScenarioHandler,
        *,
        tools: tuple[ToolHandler, ...] = (),
        model: ModelProvider | None = None,
        retriever: Retriever | None = None,
        guardrails: Mapping[GuardrailStage, Iterable[ContentGuardrail]] | None = None,
        tool_guardrails: tuple[ContentGuardrail, ...] = (),
        handoff_handlers: Mapping[str, ScenarioHandler] | None = None,
        allowed_handoffs: Mapping[str, tuple[str, ...]] | None = None,
        max_handoffs: int = 4,
    ) -> None:
        self._handler = handler
        self._registry = ToolRegistry(tuple(function_tool(tool) for tool in tools))
        self._model = model
        self._retriever = retriever
        self._guardrails = {
            GuardrailStage(stage): tuple(items) for stage, items in (guardrails or {}).items()
        }
        self._handoff_handlers = handoff_handlers
        self._allowed_handoffs = allowed_handoffs
        self._max_handoffs = max_handoffs
        legacy = tuple(tool_guardrails)
        if legacy:
            for stage in (
                GuardrailStage.RETRIEVAL,
                GuardrailStage.TOOL_INPUT,
                GuardrailStage.TOOL_OUTPUT,
            ):
                self._guardrails[stage] = (*self._guardrails.get(stage, ()), *legacy)

    async def run(
        self,
        request: RunRequest,
        *,
        run_id: str = "scenario-test-run",
    ) -> ScenarioHarnessResult:
        collector = _InvocationCollector()
        model_collector = _ModelCollector()
        pipelines = self._pipelines()
        model = self._guarded_model(model_collector, pipelines)
        runner = FunctionScenarioRunner(
            self._handler,
            tools=self._registry,
            environment=request.mode,
            tool_invocations=collector,
            model=model,
            retriever=self._retriever,
            input_guardrails=pipelines.get(GuardrailStage.INPUT),
            retrieval_guardrails=pipelines.get(GuardrailStage.RETRIEVAL),
            tool_input_guardrails=pipelines.get(GuardrailStage.TOOL_INPUT),
            tool_output_guardrails=pipelines.get(GuardrailStage.TOOL_OUTPUT),
            handoff_handlers=self._handoff_handlers,
            allowed_handoffs=self._allowed_handoffs,
            max_handoffs=self._max_handoffs,
        )
        outcome = await runner.run(run_id=run_id, request=request)
        return ScenarioHarnessResult(
            outcome=outcome,
            tool_invocations=tuple(collector.values),
            model_invocations=tuple(model_collector.values),
        )

    def _pipelines(self) -> dict[GuardrailStage, GuardrailPipeline]:
        return {
            stage: GuardrailPipeline(items) for stage, items in self._guardrails.items() if items
        }

    def _guarded_model(
        self,
        collector: _ModelCollector,
        pipelines: Mapping[GuardrailStage, GuardrailPipeline],
    ) -> ModelProvider | None:
        if self._model is None:
            return None
        instrumented: ModelProvider = InstrumentedModelProvider(self._model, collector)
        return GuardedModelProvider(
            instrumented,
            input_guardrails=pipelines.get(GuardrailStage.INPUT),
            output_guardrails=pipelines.get(GuardrailStage.OUTPUT),
        )
