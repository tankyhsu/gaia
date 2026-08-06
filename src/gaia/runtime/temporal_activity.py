"""Temporal Activities that bridge Gaia scenario computation into Workflows."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from gaia.contracts.models import (
    ErrorCode,
    RunRequest,
    RunStatus,
    ToolResult,
    ToolResultStatus,
    WriteRecoveryStrategy,
    canonical_json,
)
from gaia.guardrails import GuardrailViolation
from gaia.runtime.budget import TemporalRunBudgetStore
from gaia.runtime.dependencies import (
    RuntimeContinuation,
    RuntimeDependencies,
    RuntimeHandoff,
    RuntimeOutcome,
    SideEffectProposal,
)
from gaia.runtime.safety import (
    SafetyViolation,
    evaluate_side_effect,
    validate_run_admission,
)
from gaia.runtime.temporal_names import (
    GAIA_AUDIT_ACTIVITY,
    GAIA_COMMAND_ACTIVITY,
    GAIA_SCENARIO_ACTIVITY,
)
from gaia.spi.guardrail import GuardrailContext, GuardrailStage


def _current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


def _annotate_current_span(*, run_id: str, scenario_id: str) -> None:
    try:
        from opentelemetry import trace
    except ImportError:
        return
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("gaia.run.id", run_id)
    span.set_attribute("gaia.scenario.id", scenario_id)
    span.set_attribute("langfuse.session.id", run_id)


def _serialize_side_effect(
    proposal: SideEffectProposal,
    *,
    requires_approval: bool,
    recovery_strategy: WriteRecoveryStrategy,
    timeout_seconds: int,
    max_retries: int,
) -> dict[str, Any]:
    return {
        "step_id": proposal.step_id,
        "tool_name": proposal.tool_name,
        "payload": dict(proposal.payload),
        "reason": proposal.reason,
        "risk_level": proposal.risk_level.value,
        "depends_on": list(proposal.depends_on),
        "approval_view": (
            None
            if proposal.approval_view is None
            else proposal.approval_view.model_dump(mode="json")
        ),
        "rule_refs": list(proposal.rule_refs),
        "uncertainty_rule_refs": list(proposal.uncertainty_rule_refs),
        "requires_approval": requires_approval,
        "recovery_strategy": recovery_strategy.value,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
    }


def serialize_runtime_outcome(
    outcome: RuntimeOutcome,
    *,
    side_effect: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert the framework-neutral runner result into Temporal payload data."""

    error_code = outcome.error_code
    if isinstance(error_code, ErrorCode):
        error_code = error_code.value
    return {
        "status": outcome.status.value,
        "result": dict(outcome.result) if outcome.result is not None else None,
        "error_code": error_code,
        "decision_step": outcome.decision_step,
        "decision_rule_refs": list(outcome.decision_rule_refs),
        "pending_result": (
            None if outcome.pending_result is None else dict(outcome.pending_result)
        ),
        "continuation": (
            None
            if outcome.continuation is None
            else {
                "handler": outcome.continuation.handler,
                "input": dict(outcome.continuation.input),
                "action_result": dict(outcome.continuation.action_result),
            }
        ),
        "handoff": (
            None
            if outcome.handoff is None
            else {
                "current_agent": outcome.handoff.current_agent,
                "input": dict(outcome.handoff.input),
                "reason": outcome.handoff.reason,
                "shared_state": dict(outcome.handoff.shared_state),
                "handoff_count": outcome.handoff.handoff_count,
                "steps": [dict(step) for step in outcome.handoff.steps],
            }
        ),
        "side_effect": side_effect,
        "trace_id": _current_trace_id(),
        "trace": [
            {
                "name": step.name,
                "actor": step.actor.value,
                "source_refs": list(step.source_refs),
                "rule_refs": list(step.rule_refs),
            }
            for step in outcome.trace
        ],
    }


class TemporalRuntimeActivities:
    """Application-bound Activity implementations registered on a Gaia Worker."""

    def __init__(self, dependencies: RuntimeDependencies) -> None:
        self._dependencies = dependencies

    def _serialize_outcome(
        self,
        outcome: RuntimeOutcome,
        *,
        side_effect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        serialized = serialize_runtime_outcome(outcome, side_effect=side_effect)
        budget = self._dependencies.run_budget_store
        if isinstance(budget, TemporalRunBudgetStore):
            serialized["budget"] = budget.snapshot()
        return serialized

    async def _guard_proposal(
        self,
        *,
        run_id: str,
        request: RunRequest,
        proposal: SideEffectProposal,
    ) -> SideEffectProposal:
        pipeline = self._dependencies.tool_input_guardrails
        if pipeline is None:
            return proposal
        guarded = await pipeline.evaluate(
            canonical_json(dict(proposal.payload)),
            GuardrailContext(
                stage=GuardrailStage.TOOL_INPUT,
                run_id=run_id,
                scenario_id=request.scenario_id,
                metadata={"tool_name": proposal.tool_name},
            ),
        )
        value = json.loads(guarded)
        if not isinstance(value, dict):
            raise ApplicationError(
                "tool input guardrail must return a JSON object",
                type="GaiaTemporalGuardrailOutputInvalid",
                non_retryable=True,
            )
        return replace(proposal, payload=value)

    async def _guard_result(
        self,
        *,
        run_id: str,
        scenario_id: str,
        tool_name: str,
        result: ToolResult,
    ) -> ToolResult:
        pipeline = self._dependencies.tool_output_guardrails
        if pipeline is None or not result.data:
            return result
        guarded = await pipeline.evaluate(
            canonical_json(result.data),
            GuardrailContext(
                stage=GuardrailStage.TOOL_OUTPUT,
                run_id=run_id,
                scenario_id=scenario_id,
                metadata={"tool_name": tool_name},
            ),
        )
        value = json.loads(guarded)
        if not isinstance(value, dict):
            raise GuardrailViolation(
                "GUARDRAIL_OUTPUT_INVALID",
                "temporal_command_output",
                "tool output guardrail must return a JSON object",
            )
        return result.model_copy(update={"data": value})

    @activity.defn(name=GAIA_SCENARIO_ACTIVITY)
    async def run_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = RunRequest.model_validate(payload["request"])
        _annotate_current_span(
            run_id=payload["run_id"],
            scenario_id=request.scenario_id,
        )
        try:
            runner = self._dependencies.runner_for(request.scenario_id)
        except KeyError as error:
            raise ApplicationError(
                "scenario is not registered",
                type="GaiaScenarioNotFound",
                non_retryable=True,
            ) from error

        # Re-check admission here, inside the execution path, against the
        # server-side policy -- not because `TemporalRuntimeEngine.create` failed
        # to check, but because it is the *caller* and a caller can be skipped.
        # Anyone who can reach the Temporal namespace can start this Workflow
        # with a hand-written payload: a `mode` the deployment does not run, a
        # `user` holding roles the scenario requires. Admission that only runs
        # in the API is a check on Gaia's front door, not on execution.
        try:
            validate_run_admission(
                configured_environment=self._dependencies.environment,
                request=request,
                policy=runner.execution_policy,
            )
        except SafetyViolation as error:
            return self._serialize_outcome(
                RuntimeOutcome(
                    status=RunStatus.BLOCKED,
                    error_code=error.code,
                    decision_step="validate_request",
                )
            )
        budget = self._dependencies.run_budget_store
        if isinstance(budget, TemporalRunBudgetStore):
            prior = payload.get("budget")
            heartbeat_details = getattr(activity.info(), "heartbeat_details", ())
            if heartbeat_details and isinstance(heartbeat_details[0], dict):
                prior = heartbeat_details[0]
            budget.activate(
                payload["run_id"],
                runner.execution_policy,
                prior,
                on_change=activity.heartbeat,
            )

        continuation_payload = payload.get("continuation")
        handoff_payload = payload.get("handoff")
        if isinstance(continuation_payload, dict):
            run_continuation = getattr(runner, "run_continuation", None)
            if not callable(run_continuation):
                outcome = RuntimeOutcome(
                    status=RunStatus.BLOCKED,
                    error_code=ErrorCode.CONTINUATION_HANDLER_NOT_FOUND,
                    decision_step="resume_continuation",
                )
            else:
                outcome = await run_continuation(
                    run_id=payload["run_id"],
                    request=request,
                    continuation=RuntimeContinuation(
                        handler=str(continuation_payload["handler"]),
                        input=dict(continuation_payload.get("input", {})),
                        action_result=dict(
                            continuation_payload.get("action_result", {})
                        ),
                    ),
                )
        elif isinstance(handoff_payload, dict):
            outcome = await runner.run_handoff(
                run_id=payload["run_id"],
                request=request,
                handoff=RuntimeHandoff(
                    current_agent=str(handoff_payload["current_agent"]),
                    input=dict(handoff_payload.get("input", {})),
                    reason=str(handoff_payload["reason"]),
                    shared_state=dict(handoff_payload.get("shared_state", {})),
                    handoff_count=int(handoff_payload["handoff_count"]),
                    steps=tuple(handoff_payload.get("steps", ())),
                ),
            )
        else:
            outcome = await runner.run(run_id=payload["run_id"], request=request)
        if outcome.side_effect is not None:
            try:
                proposal = await self._guard_proposal(
                    run_id=payload["run_id"],
                    request=request,
                    proposal=outcome.side_effect,
                )
                definition = self._dependencies.write_tools.definition(proposal.tool_name)
                decision = evaluate_side_effect(
                    configured_environment=self._dependencies.environment,
                    environment_write_mode=self._dependencies.environment_write_mode,
                    request=request,
                    policy=runner.execution_policy,
                    proposal=proposal,
                    definition=definition,
                    risk_requires_approval=(
                        self._dependencies.side_effect_policy.requires_approval(
                            request,
                            proposal,
                        )
                    ),
                )
            except KeyError:
                return self._serialize_outcome(
                    RuntimeOutcome(
                        status=RunStatus.BLOCKED,
                        error_code=ErrorCode.TOOL_NOT_REGISTERED,
                        decision_step="enforce_side_effect_policy",
                    )
                )
            except (GuardrailViolation, SafetyViolation) as error:
                return self._serialize_outcome(
                    RuntimeOutcome(
                        status=RunStatus.BLOCKED,
                        error_code=(
                            ErrorCode.GUARDRAIL_BLOCKED
                            if isinstance(error, GuardrailViolation)
                            else error.code
                        ),
                        decision_step="enforce_side_effect_policy",
                    )
                )
            return self._serialize_outcome(
                replace(outcome, side_effect=proposal),
                side_effect=_serialize_side_effect(
                    proposal,
                    requires_approval=decision.requires_approval,
                    recovery_strategy=(
                        decision.definition.recovery_strategy
                        or (
                            WriteRecoveryStrategy.IDEMPOTENT
                            if decision.definition.idempotent
                            else WriteRecoveryStrategy.RECONCILABLE
                        )
                    ),
                    timeout_seconds=decision.definition.timeout_seconds,
                    max_retries=decision.definition.max_retries,
                ),
            )
        if outcome.handoff is not None:
            return self._serialize_outcome(outcome)
        if outcome.status not in {
            RunStatus.SUCCEEDED,
            RunStatus.BLOCKED,
            RunStatus.DEGRADED,
            RunStatus.FAILED,
        }:
            raise ApplicationError(
                f"runner returned non-terminal status {outcome.status.value!r}",
                type="GaiaTemporalOutcomeNotTerminal",
                non_retryable=True,
            )
        return self._serialize_outcome(outcome)

    @activity.defn(name=GAIA_AUDIT_ACTIVITY)
    async def record_audit(self, payload: dict[str, Any]) -> None:
        """Project one Run's evidence into Gaia's own durable store.

        This Activity is the only writer of the audit projection. It is
        idempotent by `(run_id, sequence)` and `gate_id`, because Temporal is
        entitled to retry it -- and because the Workflow deliberately retries it
        forever rather than let a Run reach a terminal state whose only record
        lives inside Temporal's retention window.

        A missing projection is a configuration failure, not a degraded mode:
        Gaia refuses to pretend a Run was audited when no store was wired.
        """

        projection = self._dependencies.audit_projection
        if projection is None:
            raise ApplicationError(
                "no audit projection is configured; Gaia cannot record Run evidence "
                "outside Temporal's retention window",
                type="GaiaAuditProjectionMissing",
                non_retryable=True,
            )
        snapshot = payload["snapshot"]
        events = payload["events"]
        gates = payload["gates"]
        if not isinstance(snapshot, dict) or not isinstance(events, list):
            raise ApplicationError(
                "audit payload must carry a snapshot object and an event list",
                type="GaiaAuditPayloadInvalid",
                non_retryable=True,
            )
        await projection.record(
            snapshot=snapshot,
            events=events,
            gates=list(gates) if isinstance(gates, list) else [],
        )

    async def _unapproved_gate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Refuse an approval-gated write the audit projection cannot vouch for.

        The Workflow decides *that* a gate was approved, but the Workflow is
        reachable by anyone who can talk to the Temporal namespace, and its
        `decide` Update believes the `roles` in its own payload. Trusting it
        would make namespace access equivalent to approver authority over every
        high-risk write Gaia guards.

        So the last check before the side effect runs asks Gaia's own database,
        which only the authenticated API can write an approval into. A forged
        Update can still move the Workflow's internal state; it cannot make the
        write happen.
        """

        gate_id = payload.get("gate_id")
        if not payload.get("requires_approval") or not isinstance(gate_id, str):
            return None
        projection = self._dependencies.audit_projection
        if projection is None:
            raise ApplicationError(
                "an approval-gated write needs an audit projection to verify the "
                "decision against; refusing to execute it unverified",
                type="GaiaAuditProjectionMissing",
                non_retryable=True,
            )
        gate = await projection.get_gate(gate_id)
        if gate is not None and gate.get("status") == "approved":
            return None
        activity.logger.warning(
            "refusing gated write %s: Gaia has no authenticated approval for gate %s",
            payload.get("command_id"),
            gate_id,
        )
        return {
            **ToolResult(
                ok=False,
                status=ToolResultStatus.FAILED,
                data={},
                error_code=ErrorCode.GATE_DECISION_UNVERIFIED,
            ).model_dump(mode="json"),
            "trace_id": _current_trace_id(),
        }

    @activity.defn(name=GAIA_COMMAND_ACTIVITY)
    async def execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one policy-authorized write under Temporal retry ownership."""

        _annotate_current_span(
            run_id=payload["run_id"],
            scenario_id=payload["scenario_id"],
        )
        proposal = payload["proposal"]
        tool_name = proposal["tool_name"]
        unauthorized = await self._unapproved_gate(payload)
        if unauthorized is not None:
            return unauthorized
        try:
            adapter = self._dependencies.write_tools.create(
                tool_name,
                proposal["payload"],
            )
        except (KeyError, ValueError) as error:
            raise ApplicationError(
                str(error),
                type="GaiaTemporalWriteAdapterInvalid",
                non_retryable=True,
            ) from error

        strategy = adapter.definition.recovery_strategy or (
            WriteRecoveryStrategy.IDEMPOTENT
            if adapter.definition.idempotent
            else WriteRecoveryStrategy.RECONCILABLE
        )
        if activity.info().attempt > 1 and strategy == WriteRecoveryStrategy.RECONCILABLE:
            reconciled = await adapter.reconcile(
                idempotency_key=payload["command_id"]
            )
            result = reconciled or ToolResult(
                ok=False,
                status=ToolResultStatus.UNKNOWN,
                data={},
                error_code=ErrorCode.SIDE_EFFECT_UNKNOWN,
            )
        else:
            result = await adapter.execute(
                payload=proposal["payload"],
                idempotency_key=payload["command_id"],
            )
            if (
                result.status == ToolResultStatus.UNKNOWN
                and strategy == WriteRecoveryStrategy.RECONCILABLE
            ):
                reconciled = await adapter.reconcile(
                    idempotency_key=payload["command_id"]
                )
                if reconciled is not None:
                    result = reconciled

        try:
            result = await self._guard_result(
                run_id=payload["run_id"],
                scenario_id=payload["scenario_id"],
                tool_name=tool_name,
                result=result,
            )
        except GuardrailViolation:
            result = ToolResult(
                ok=False,
                status=ToolResultStatus.FAILED,
                data={},
                error_code=ErrorCode.GUARDRAIL_BLOCKED,
            )
        return {
            **result.model_dump(mode="json"),
            "trace_id": _current_trace_id(),
        }
