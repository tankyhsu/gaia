"""Application runner for the controlled-task reference example."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.types import Command

from examples.controlled_task.context import MockContextProvider
from examples.controlled_task.model import DeterministicMockProvider
from examples.controlled_task.models import ControlledTaskIntent
from examples.controlled_task.read_tool import DEFAULT_RESOURCES
from examples.controlled_task.workflow import build_controlled_task_graph
from gaia.contracts.models import (
    ActorType,
    ErrorCode,
    ExecutionPolicy,
    ModelCapabilities,
    ModelEndpointProfile,
    RiskLevel,
    RunRequest,
    RunStatus,
    VersionBundle,
)
from gaia.runtime.dependencies import (
    RuntimeOutcome,
    RuntimeTraceStep,
    SideEffectProposal,
)
from gaia.sdk.context import ContextQuery, RunSession
from gaia.sdk.model import ModelCallContext, ModelMessage, ModelProvider

SCENARIO_PATH = Path(__file__).parent / "specs" / "scenario.json"


def model_profile() -> ModelEndpointProfile:
    return ModelEndpointProfile(
        provider_id="mock",
        protocol="mock",
        model_id="deterministic-mock",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=False,
            max_context_tokens=None,
        ),
        data_residency="local",
        timeout_seconds=2,
    )


class ControlledTaskRunner:
    def __init__(
        self,
        resources: dict[str, dict[str, Any]] | None = None,
        workflow: Any | None = None,
        model_provider: ModelProvider | None = None,
    ) -> None:
        scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        self._execution_policy = ExecutionPolicy.model_validate(
            {"scenario_id": scenario["scenario_id"], **scenario["policy"]}
        )
        self.resources = (
            resources
            if resources is not None
            else {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
        )
        self._workflow = workflow or build_controlled_task_graph()
        self._durable_workflow = workflow is not None
        self._model_provider = model_provider or DeterministicMockProvider()

    @property
    def version_bundle(self) -> VersionBundle:
        return VersionBundle(
            policy="policy-controlled-task:1.0.0",
            workflow="1.0.0",
            rules="1.0.0",
            prompt="1.0.0",
            model_profile="1.0.0",
            toolset="1.0.0",
            context_profile="1.0.0",
        )

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return self._execution_policy

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        intent_result = await self._model_provider.generate_structured(
            profile=model_profile(),
            messages=[ModelMessage(role="user", content=request.request.text)],
            output_schema=ControlledTaskIntent,
            timeout_seconds=2,
            context=ModelCallContext(
                run_id=run_id,
                scenario_id=request.scenario_id,
                prompt_version=self.version_bundle.prompt,
            ),
        )
        intent = ControlledTaskIntent.model_validate(intent_result.output)
        resource = self.resources.get(intent.resource_id or "")
        context = await MockContextProvider(
            str(request.request.metadata.get("context_mode", "normal"))
        ).get_context(
            session=RunSession(
                run_id=run_id,
                user_id=request.user.id,
                organization=request.user.organization,
                roles=request.user.roles,
            ),
            query=ContextQuery(
                organization=request.user.organization,
                resource_id=intent.resource_id,
            ),
        )
        trace = (
            RuntimeTraceStep("interpret_intent", ActorType.MODEL),
            RuntimeTraceStep("read_resource", ActorType.TOOL),
            RuntimeTraceStep("authorize_context", ActorType.RULE),
            RuntimeTraceStep(
                "load_context",
                source_refs=tuple(item.source_id for item in context.documents),
            ),
        )
        workflow_state = self._workflow.invoke(
            {
                "run_id": run_id,
                "request_text": request.request.text,
                "intent": intent.model_dump(mode="json"),
                "user": request.user.model_dump(mode="json"),
                "resource": resource,
                "context_gaps": context.gaps,
                "visited": [],
            },
            self._workflow_config(run_id),
        )
        outcome = str(workflow_state["outcome"])
        rule = str(workflow_state["rule_id"])
        if outcome in {"blocked", "degraded"}:
            return RuntimeOutcome(
                status=RunStatus.DEGRADED if outcome == "degraded" else RunStatus.BLOCKED,
                error_code=ErrorCode(str(workflow_state["error_code"])),
                trace=trace,
                decision_step="evaluate_rules",
                decision_rule_refs=(rule,),
            )
        if outcome in {"read", "no_change"}:
            step = "return_read_result" if outcome == "read" else "return_no_change"
            return RuntimeOutcome(
                status=RunStatus.SUCCEEDED,
                result=dict(workflow_state["result"]),
                trace=(*trace, RuntimeTraceStep(step, rule_refs=(rule,))),
                decision_step="evaluate_rules",
                decision_rule_refs=(rule,),
            )

        proposal = dict(workflow_state["proposal"])
        proposal["write_adapter_mode"] = str(
            request.request.metadata.get("write_adapter_mode", "normal")
        )
        return RuntimeOutcome(
            status=RunStatus.RUNNING,
            trace=(*trace, RuntimeTraceStep("propose_side_effect", rule_refs=(rule,))),
            side_effect=SideEffectProposal(
                step_id="execute_side_effect",
                tool_name="set_resource_status",
                payload=proposal,
                reason=intent.reason or "approval required",
                risk_level=RiskLevel.HIGH,
                rule_refs=(rule,),
                uncertainty_rule_refs=("RULE-CT-010",),
            ),
        )

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        if self._durable_workflow:
            self._workflow.update_state(self._workflow_config(run_id), {"gate_id": gate_id})

    def resume(self, *, run_id: str, decision: str) -> None:
        if self._durable_workflow:
            self._workflow.invoke(
                Command(resume={"decision": decision}),
                self._workflow_config(run_id),
            )

    @staticmethod
    def _workflow_config(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}
