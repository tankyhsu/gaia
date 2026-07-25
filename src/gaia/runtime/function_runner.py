"""ScenarioRunner adapter for ordinary async Python functions."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from gaia.contracts.models import ExecutionPolicy, RunRequest, RunStatus, VersionBundle
from gaia.runtime.dependencies import (
    RuntimeOutcome,
    RuntimeTraceStep,
    SideEffectProposal,
)
from gaia.sdk.scenario import (
    ScenarioContext,
    ScenarioHandler,
    ScenarioResponse,
    ScenarioSpec,
    get_scenario_spec,
)


class FunctionScenarioRunner:
    """Adapt a decorated async function to Gaia's sole runtime SPI."""

    def __init__(self, handler: ScenarioHandler, spec: ScenarioSpec | None = None) -> None:
        self._handler = handler
        self._spec = spec or get_scenario_spec(handler)
        if self._spec.handler is not handler:
            raise ValueError("scenario spec handler does not match the supplied function")

    @property
    def version_bundle(self) -> VersionBundle:
        return self._spec.version_bundle

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return self._spec.execution_policy

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        value = await self._handler(ScenarioContext(run_id=run_id, request=request))
        if isinstance(value, ScenarioResponse):
            return RuntimeOutcome(
                status=value.status,
                result=dict(value.result) if value.result is not None else None,
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
                        rule_refs=value.side_effect.rule_refs,
                        uncertainty_rule_refs=value.side_effect.uncertainty_rule_refs,
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

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        del run_id, gate_id

    def resume(self, *, run_id: str, decision: str) -> None:
        del run_id, decision
