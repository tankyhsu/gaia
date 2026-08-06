"""Development-only in-process Runtime with Gaia-owned SQL evidence.

The in-process provider is intentionally small and not a production deployment
option: it executes one scenario step in the API process and persists the
resulting Run and event trail through Gaia's audit projection. Application-owned
LangGraph graphs may still use their own checkpointer. Cross-process recovery,
HumanGate waits, side-effect command retries, and long-running orchestration
remain Temporal responsibilities.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from gaia.contracts.models import (
    ActorType,
    ErrorCode,
    ErrorResponse,
    EventStatus,
    HumanGate,
    HumanGateDecisionRequest,
    RunEvent,
    RunPage,
    RunRequest,
    RunSnapshot,
    RunStatus,
    request_hash,
)
from gaia.diagnostics.error_catalog import operational_error
from gaia.runtime.budget import InProcessRunBudgetStore
from gaia.runtime.contracts import (
    AuditProjection,
    RuntimeConflict,
    RuntimePermissionDenied,
    RuntimeRunNotFound,
)
from gaia.runtime.dependencies import RuntimeDependencies
from gaia.runtime.safety import SafetyViolation, validate_run_admission

_TERMINAL = {
    RunStatus.SUCCEEDED,
    RunStatus.BLOCKED,
    RunStatus.DEGRADED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


class InProcessRuntimeEngine:
    """Execute development and PoC scenarios locally and persist their evidence.

    An in-process Run completes inside the request process. When a scenario proposes
    a side effect or handoff, the Run is blocked with
    ``DURABLE_EXECUTION_REQUIRED`` instead of silently providing weaker
    recovery or approval semantics than the application requested.
    """

    def __init__(
        self,
        *,
        dependencies: RuntimeDependencies,
        audit_projection: AuditProjection,
    ) -> None:
        self._dependencies = dependencies
        self._audit = audit_projection

    async def create(self, request: RunRequest, idempotency_key: str) -> RunSnapshot:
        try:
            runner = self._dependencies.runner_for(request.scenario_id)
        except KeyError as missing_runner:
            raise RuntimeConflict(ErrorCode.SCENARIO_NOT_FOUND.value) from missing_runner
        try:
            validate_run_admission(
                configured_environment=self._dependencies.environment,
                request=request,
                policy=runner.execution_policy,
            )
        except SafetyViolation as violation:
            raise RuntimePermissionDenied(violation.code.value) from violation

        digest = request_hash(request)
        run_id = self._run_id(request, idempotency_key)
        existing = await self._audit.get_run(run_id)
        if existing is not None:
            projected_events = await self._audit.events_after(run_id)
            original = next(
                (
                    self._request_hash_from_event(event)
                    for event in projected_events
                    if event.get("step") == "run.created"
                ),
                "",
            )
            if original != digest:
                raise RuntimeConflict(ErrorCode.IDEMPOTENCY_CONFLICT.value)
            return RunSnapshot.model_validate(existing)

        trace_id = str(uuid4())
        created_at = datetime.now(UTC)
        version_bundle = await self._dependencies.version_resolver.resolve(
            request,
            runner.version_bundle,
        )
        run_events: list[RunEvent] = []

        def record(
            step: str,
            *,
            actor: ActorType = ActorType.SYSTEM,
            status: EventStatus = EventStatus.SUCCEEDED,
            source_refs: list[str] | None = None,
            rule_refs: list[str] | None = None,
            error_code: ErrorCode | str | None = None,
            details: dict[str, object] | None = None,
        ) -> None:
            run_events.append(
                RunEvent(
                    event_id=str(uuid4()),
                    run_id=run_id,
                    sequence=len(run_events) + 1,
                    timestamp=datetime.now(UTC),
                    actor=actor,
                    step=step,
                    status=status,
                    source_refs=source_refs or [],
                    rule_refs=rule_refs or [],
                    error_code=error_code,
                    details=details or {},
                )
            )

        record("run.created", details={"request_hash": digest, "provider": "in_process"})
        record("validate_request", actor=ActorType.RULE)
        record("start_local_execution")
        result: dict[str, object] | None = None
        error_response: ErrorResponse | None = None
        try:
            budget = self._dependencies.run_budget_store
            if isinstance(budget, InProcessRunBudgetStore):
                budget.activate(run_id, runner.execution_policy)
            outcome = await runner.run(run_id=run_id, request=request)
            for step in outcome.trace:
                record(
                    step.name,
                    actor=step.actor,
                    source_refs=list(step.source_refs),
                    rule_refs=list(step.rule_refs),
                )
            if outcome.side_effect is not None or outcome.handoff is not None:
                status = RunStatus.BLOCKED
                error_response = operational_error(
                    ErrorCode.DURABLE_EXECUTION_REQUIRED,
                    trace_id=trace_id,
                    details={
                        "provider": "in_process",
                        "requested_capability": (
                            "side_effect" if outcome.side_effect is not None else "handoff"
                        ),
                    },
                )
                record(
                    "require_durable_execution",
                    actor=ActorType.RULE,
                    status=EventStatus.BLOCKED,
                    error_code=ErrorCode.DURABLE_EXECUTION_REQUIRED,
                )
            else:
                status = outcome.status
                result = dict(outcome.result) if outcome.result is not None else None
                record(
                    outcome.decision_step,
                    actor=ActorType.RULE,
                    status=(
                        EventStatus.BLOCKED
                        if status == RunStatus.BLOCKED
                        else EventStatus.FAILED
                        if status == RunStatus.FAILED
                        else EventStatus.SUCCEEDED
                    ),
                    rule_refs=list(outcome.decision_rule_refs),
                    error_code=outcome.error_code,
                )
                if outcome.error_code is not None:
                    error_response = operational_error(outcome.error_code, trace_id=trace_id)
        except Exception:
            status = RunStatus.FAILED
            error_response = operational_error(ErrorCode.INTERNAL_ERROR, trace_id=trace_id)
            record(
                "local_execution",
                status=EventStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
            )

        updated_at = datetime.now(UTC)
        snapshot = RunSnapshot(
            run_id=run_id,
            trace_id=trace_id,
            scenario_id=request.scenario_id,
            mode=request.mode,
            status=status,
            user=request.user,
            version_bundle=version_bundle,
            result=result,
            error=error_response,
            created_at=created_at,
            updated_at=updated_at,
        )
        await self._audit.record(
            snapshot=snapshot.model_dump(mode="json"),
            events=[event.model_dump(mode="json") for event in run_events],
            gates=[],
        )
        return snapshot

    async def decide(
        self,
        gate_id: str,
        body: HumanGateDecisionRequest,
    ) -> RunSnapshot:
        del gate_id, body
        raise RuntimeConflict(ErrorCode.DURABLE_EXECUTION_REQUIRED.value)

    async def cancel(self, run_id: str, reason: str) -> RunSnapshot:
        del reason
        snapshot = await self.inspect(run_id)
        if snapshot.status in _TERMINAL:
            raise RuntimeConflict("RUN_NOT_CANCELLABLE")
        raise RuntimeConflict(ErrorCode.DURABLE_EXECUTION_REQUIRED.value)

    async def inspect(self, run_id: str) -> RunSnapshot:
        value = await self._audit.get_run(run_id)
        if value is None:
            raise RuntimeRunNotFound(run_id)
        return RunSnapshot.model_validate(value)

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> RunPage:
        value = await self._audit.list_runs(
            organization=organization,
            status=None if status is None else status.value,
            scenario_id=scenario_id,
            limit=limit,
            cursor=cursor,
        )
        return RunPage.model_validate(value)

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]:
        if await self._audit.get_run(run_id) is None:
            raise RuntimeRunNotFound(run_id)
        return [
            RunEvent.model_validate(value)
            for value in await self._audit.events_after(run_id, sequence)
        ]

    async def get_gate(self, gate_id: str) -> HumanGate:
        value = await self._audit.get_gate(gate_id)
        if value is None:
            raise RuntimeRunNotFound(gate_id)
        return HumanGate.model_validate(value)

    async def gates_for_run(self, run_id: str) -> list[HumanGate]:
        await self.inspect(run_id)
        return [
            HumanGate.model_validate(value)
            for value in await self._audit.gates_for_run(run_id)
        ]

    @staticmethod
    def _run_id(request: RunRequest, idempotency_key: str) -> str:
        identity = f"{request.user.organization}\0{idempotency_key}".encode()
        return f"in-process-{hashlib.sha256(identity).hexdigest()[:32]}"

    @staticmethod
    def _request_hash_from_event(event: dict[str, object]) -> str:
        details = event.get("details")
        return str(details.get("request_hash", "")) if isinstance(details, dict) else ""
