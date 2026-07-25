"""Transactional runtime for Gaia applications."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.contracts.models import (
    ActorType,
    CommandStatus,
    Decision,
    ErrorCode,
    ErrorResponse,
    EventStatus,
    GateStatus,
    HumanGate,
    HumanGateDecisionRequest,
    RiskLevel,
    RunEvent,
    RunMode,
    RunRequest,
    RunSnapshot,
    RunStatus,
    ToolResult,
    ToolResultStatus,
    UserIdentity,
    VersionBundle,
    request_hash,
)
from gaia.diagnostics.error_catalog import operational_error
from gaia.persistence.models import (
    HumanGateRecord,
    IdempotencyRecord,
    RunEventRecord,
    RunRecord,
    SideEffectCommandRecord,
)
from gaia.runtime.dependencies import RuntimeDependencies, SideEffectProposal
from gaia.runtime.human_gates import (
    GateDecisionConflict,
    GatePermissionDenied,
    decide_gate,
)
from gaia.runtime.lifecycle import InvalidStateTransition, validate_transition
from gaia.runtime.safety import SafetyViolation, evaluate_side_effect, validate_run_admission
from gaia.runtime.side_effects import command_idempotency_key
from gaia.sdk.tool import WriteAdapter


class RuntimeConflict(ValueError):
    """The requested operation conflicts with persisted runtime state."""


class RuntimePermissionDenied(ValueError):
    """The caller cannot perform the requested runtime operation."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_aware(value: datetime) -> datetime:
    aware = _aware(value)
    if aware is None:  # pragma: no cover - narrows the type for static checking
        raise ValueError("required datetime is missing")
    return aware


class PersistentRuntimeEngine:
    """The sole owner of Run, event, gate and command state transitions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dependencies: RuntimeDependencies,
    ) -> None:
        self._session_factory = session_factory
        self._dependencies = dependencies
        self._adapters: dict[str, WriteAdapter] = {}
        self._side_effect_success_count = 0

    @property
    def side_effect_success_count(self) -> int:
        return self._side_effect_success_count

    async def create(self, request: RunRequest, idempotency_key: str) -> RunSnapshot:
        try:
            runner = self._dependencies.runner_for(request.scenario_id)
        except KeyError as error:
            raise RuntimeConflict(ErrorCode.SCENARIO_NOT_FOUND.value) from error
        execution_policy = runner.execution_policy
        try:
            validate_run_admission(
                configured_environment=self._dependencies.environment,
                request=request,
                policy=execution_policy,
            )
        except SafetyViolation as error:
            raise RuntimePermissionDenied(error.code.value) from error
        digest = request_hash(request)
        existing = await self._idempotent_run(idempotency_key, digest)
        if existing is not None:
            return existing
        version_bundle = await self._dependencies.version_resolver.resolve(
            request,
            runner.version_bundle,
        )
        try:
            snapshot, created = await self._create_received(
                request,
                idempotency_key=idempotency_key,
                request_digest=digest,
                version_bundle=version_bundle.model_dump(mode="json"),
            )
        except IntegrityError:
            async with self._session_factory() as session:
                existing = await session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.scope == "runs",
                        IdempotencyRecord.key == idempotency_key,
                    )
                )
                if existing is None:
                    raise
                if existing.request_hash != digest:
                    raise RuntimeConflict(ErrorCode.IDEMPOTENCY_CONFLICT.value) from None
                record = await session.get(RunRecord, existing.run_id)
                if record is None:
                    raise RuntimeError("idempotency record references missing Run") from None
                return self._snapshot(record)
        if not created:
            return snapshot

        await self._transition(snapshot.run_id, RunStatus.VALIDATED, "validate_request")
        await self._transition(snapshot.run_id, RunStatus.RUNNING, "start_workflow")
        try:
            outcome = await runner.run(run_id=snapshot.run_id, request=request)
            for step in outcome.trace:
                await self._record_step(
                    snapshot.run_id,
                    step.name,
                    actor=step.actor,
                    source_refs=list(step.source_refs),
                    rule_refs=list(step.rule_refs),
                )
        except Exception:  # Application failures become durable runtime failures.
            return await self._finish(
                snapshot.run_id,
                RunStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                decision_step="application_runner",
                rule_refs=[],
            )
        if outcome.side_effect is None:
            return await self._finish(
                snapshot.run_id,
                outcome.status,
                result=dict(outcome.result) if outcome.result is not None else None,
                error_code=outcome.error_code,
                decision_step=outcome.decision_step,
                rule_refs=list(outcome.decision_rule_refs),
            )

        proposal = outcome.side_effect
        payload = dict(proposal.payload)
        try:
            definition = self._dependencies.write_tools.definition(proposal.tool_name)
        except KeyError:
            return await self._finish(
                snapshot.run_id,
                RunStatus.BLOCKED,
                error_code=ErrorCode.TOOL_NOT_REGISTERED,
                decision_step="enforce_side_effect_policy",
                rule_refs=list(proposal.rule_refs),
            )
        try:
            decision = evaluate_side_effect(
                configured_environment=self._dependencies.environment,
                environment_write_mode=self._dependencies.environment_write_mode,
                request=request,
                policy=execution_policy,
                proposal=proposal,
                definition=definition,
                risk_requires_approval=self._dependencies.side_effect_policy.requires_approval(
                    request, proposal
                ),
            )
        except SafetyViolation as error:
            return await self._finish(
                snapshot.run_id,
                RunStatus.BLOCKED,
                error_code=error.code,
                decision_step="enforce_side_effect_policy",
                rule_refs=list(proposal.rule_refs),
            )
        command_id = command_idempotency_key(
            scenario_id=request.scenario_id,
            workflow_version=snapshot.version_bundle.workflow,
            run_id=snapshot.run_id,
            step_id=proposal.step_id,
            tool_name=proposal.tool_name,
            payload=payload,
        )
        if not decision.requires_approval:
            await self._create_approved_command(
                run_id=snapshot.run_id,
                command_id=command_id,
                proposal=proposal,
            )
            return await self._execute_command(command_id)
        waiting = await self._create_gate(
            run_id=snapshot.run_id,
            command_id=command_id,
            requested_by=request.user.id,
            proposal=proposal,
        )
        try:
            runner.bind_gate(run_id=snapshot.run_id, gate_id=waiting.pending_gate_id or "")
        except Exception:
            await self._record_failure_event(snapshot.run_id, "application_bind_gate")
        return waiting

    async def decide(self, gate_id: str, body: HumanGateDecisionRequest) -> RunSnapshot:
        should_execute = False
        workflow_decision: str | None = None
        run_id = ""
        command_id = ""
        async with self._session_factory.begin() as session:
            gate = await session.get(HumanGateRecord, gate_id, with_for_update=True)
            if gate is None:
                raise KeyError(gate_id)
            run = await session.get(RunRecord, gate.run_id, with_for_update=True)
            command = await session.get(
                SideEffectCommandRecord, gate.command_id, with_for_update=True
            )
            if run is None or command is None:
                raise RuntimeError("gate references missing runtime records")
            run_id, command_id = run.run_id, command.command_id
            _, command_rule_refs, _ = self._command_parts(command.payload_json)
            current = self._gate(gate)
            if current.status == GateStatus.PENDING and _now() >= current.expires_at:
                decided = current.model_copy(update={"status": GateStatus.EXPIRED})
            else:
                try:
                    decided = decide_gate(
                        current,
                        decision=body.decision,
                        decided_by=body.decided_by,
                        roles=body.roles,
                        comment=body.comment,
                        now=_now(),
                    )
                except GatePermissionDenied as error:
                    raise RuntimePermissionDenied("FORBIDDEN") from error
                except GateDecisionConflict as error:
                    raise RuntimeConflict("GATE_DECISION_CONFLICT") from error

            if current.status != GateStatus.PENDING:
                if run.status in {item.value for item in _TERMINAL_STATUSES}:
                    return self._snapshot(run)
                # A repeated approval must not reconcile a command that another Runtime is
                # currently executing. It observes the in-flight snapshot instead.
                should_execute = command.status == CommandStatus.APPROVED.value
            else:
                gate.status = decided.status.value
                gate.decided_by = decided.decided_by
                gate.comment = decided.comment
                gate.decided_at = decided.decided_at
                if decided.status == GateStatus.EXPIRED:
                    workflow_decision = "rejected"
                    command.status = CommandStatus.REJECTED.value
                    self._set_run_error(run, RunStatus.BLOCKED, ErrorCode.HUMAN_GATE_EXPIRED)
                    await self._append_event(
                        session,
                        run_id,
                        "human_gate_expired",
                        EventStatus.BLOCKED,
                        actor=ActorType.SYSTEM,
                        rule_refs=command_rule_refs,
                        error_code=ErrorCode.HUMAN_GATE_EXPIRED,
                    )
                elif body.decision == Decision.REJECTED:
                    workflow_decision = "rejected"
                    command.status = CommandStatus.REJECTED.value
                    self._set_run_error(run, RunStatus.BLOCKED, ErrorCode.HUMAN_GATE_REJECTED)
                    await self._append_event(
                        session,
                        run_id,
                        "human_gate_rejected",
                        EventStatus.BLOCKED,
                        actor=ActorType.HUMAN,
                        rule_refs=command_rule_refs,
                        error_code=ErrorCode.HUMAN_GATE_REJECTED,
                    )
                else:
                    workflow_decision = "approved"
                    validate_transition(RunStatus(run.status), RunStatus.RUNNING)
                    run.status = RunStatus.RUNNING.value
                    run.updated_at = _now()
                    command.status = CommandStatus.APPROVED.value
                    command.updated_at = _now()
                    await self._append_event(
                        session,
                        run_id,
                        "human_gate_approved",
                        EventStatus.SUCCEEDED,
                        actor=ActorType.HUMAN,
                        rule_refs=command_rule_refs,
                    )
                    should_execute = True

        if workflow_decision:
            runner = self._dependencies.runner_for((await self.inspect(run_id)).scenario_id)
            try:
                runner.resume(run_id=run_id, decision=workflow_decision)
            except Exception:
                await self._record_failure_event(run_id, "application_resume")
        if should_execute:
            return await self._execute_command(command_id)
        return await self.inspect(run_id)

    async def cancel(self, run_id: str, reason: str) -> RunSnapshot:
        async with self._session_factory.begin() as session:
            run = await session.get(RunRecord, run_id, with_for_update=True)
            if run is None:
                raise KeyError(run_id)
            try:
                validate_transition(RunStatus(run.status), RunStatus.CANCELLED)
            except InvalidStateTransition as error:
                raise RuntimeConflict("RUN_NOT_CANCELLABLE") from error
            run.status = RunStatus.CANCELLED.value
            run.pending_gate_id = None
            run.updated_at = _now()
            run.result_json = {"cancel_reason": reason}
            await self._append_event(
                session, run_id, "cancel", EventStatus.SUCCEEDED, actor=ActorType.HUMAN
            )
        return await self.inspect(run_id)

    async def transition(self, *, run_id: str, status: RunStatus, step: str) -> None:
        """Public transition hook used by runtime services and transaction tests."""
        await self._transition(run_id, status, step)

    async def inspect(self, run_id: str) -> RunSnapshot:
        async with self._session_factory() as session:
            record = await session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(run_id)
            return self._snapshot(record)

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]:
        async with self._session_factory() as session:
            if await session.get(RunRecord, run_id) is None:
                raise KeyError(run_id)
            records = await session.scalars(
                select(RunEventRecord)
                .where(RunEventRecord.run_id == run_id, RunEventRecord.sequence > sequence)
                .order_by(RunEventRecord.sequence)
            )
            return [self._event(item) for item in records]

    async def startup_recover(self) -> list[str]:
        """Reconcile persisted write uncertainty before returning resumable Runs."""
        async with self._session_factory() as session:
            commands = await session.scalars(
                select(SideEffectCommandRecord.command_id)
                .join(RunRecord, RunRecord.run_id == SideEffectCommandRecord.run_id)
                .where(
                    SideEffectCommandRecord.status.in_(
                        [
                            CommandStatus.APPROVED.value,
                            CommandStatus.EXECUTING.value,
                            CommandStatus.UNKNOWN.value,
                        ]
                    ),
                    RunRecord.status.in_([RunStatus.RUNNING.value, RunStatus.WAITING_HUMAN.value]),
                )
            )
            command_ids = list(commands)
        for command_id in command_ids:
            await self._execute_command(command_id)
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(RunRecord).where(
                    RunRecord.status.in_([RunStatus.RUNNING.value, RunStatus.WAITING_HUMAN.value])
                )
            )
            return [item.run_id for item in rows]

    async def get_gate(self, gate_id: str) -> HumanGate:
        async with self._session_factory() as session:
            record = await session.get(HumanGateRecord, gate_id)
            if record is None:
                raise KeyError(gate_id)
            return self._gate(record)

    async def get_command(self, command_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            record = await session.get(SideEffectCommandRecord, command_id)
            if record is None:
                raise KeyError(command_id)
            payload, _, _ = self._command_parts(record.payload_json)
            return {
                "command_id": record.command_id,
                "run_id": record.run_id,
                "tool_name": record.tool_name,
                "idempotency_key": record.idempotency_key,
                "status": record.status,
                "payload": payload,
                "result": record.result_json,
            }

    async def _create_received(
        self,
        request: RunRequest,
        *,
        idempotency_key: str,
        request_digest: str,
        version_bundle: dict[str, Any],
    ) -> tuple[RunSnapshot, bool]:
        async with self._session_factory.begin() as session:
            existing = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == "runs",
                    IdempotencyRecord.key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != request_digest:
                    raise RuntimeConflict(ErrorCode.IDEMPOTENCY_CONFLICT.value)
                record = await session.get(RunRecord, existing.run_id)
                if record is None:
                    raise RuntimeError("idempotency record references missing Run")
                return self._snapshot(record), False

            now = _now()
            run_id = str(uuid4())
            record = RunRecord(
                run_id=run_id,
                scenario_id=request.scenario_id,
                mode=request.mode.value,
                status=RunStatus.RECEIVED.value,
                user_json=request.user.model_dump(mode="json"),
                request_json=request.request.model_dump(mode="json"),
                version_bundle=version_bundle,
                result_json=None,
                error_json=None,
                pending_gate_id=None,
                trace_id=run_id,
                event_sequence=0,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            # These models intentionally have no ORM relationship. Flush the parent first so
            # databases with immediate foreign-key checks see the run before its idempotency row.
            await session.flush()
            session.add(
                IdempotencyRecord(
                    scope="runs",
                    key=idempotency_key,
                    request_hash=request_digest,
                    run_id=run_id,
                    created_at=now,
                )
            )
            await session.flush()
            await self._append_event(
                session, run_id, "received", EventStatus.STARTED, actor=ActorType.SYSTEM
            )
            return self._snapshot(record), True

    async def _idempotent_run(
        self,
        idempotency_key: str,
        request_digest: str,
    ) -> RunSnapshot | None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == "runs",
                    IdempotencyRecord.key == idempotency_key,
                )
            )
            if existing is None:
                return None
            if existing.request_hash != request_digest:
                raise RuntimeConflict(ErrorCode.IDEMPOTENCY_CONFLICT.value)
            record = await session.get(RunRecord, existing.run_id)
            if record is None:
                raise RuntimeError("idempotency record references missing Run")
            return self._snapshot(record)

    async def _transition(self, run_id: str, status: RunStatus, step: str) -> None:
        async with self._session_factory.begin() as session:
            run = await session.get(RunRecord, run_id, with_for_update=True)
            if run is None:
                raise KeyError(run_id)
            validate_transition(RunStatus(run.status), status)
            run.status = status.value
            run.updated_at = _now()
            await self._append_event(
                session, run_id, step, EventStatus.SUCCEEDED, actor=ActorType.SYSTEM
            )

    async def _record_step(
        self,
        run_id: str,
        step: str,
        *,
        actor: ActorType = ActorType.SYSTEM,
        source_refs: list[str] | None = None,
        rule_refs: list[str] | None = None,
    ) -> None:
        async with self._session_factory.begin() as session:
            if await session.get(RunRecord, run_id) is None:
                raise KeyError(run_id)
            await self._append_event(
                session,
                run_id,
                step,
                EventStatus.STARTED,
                actor=actor,
                source_refs=source_refs,
                rule_refs=rule_refs,
            )
            await self._append_event(
                session,
                run_id,
                step,
                EventStatus.SUCCEEDED,
                actor=actor,
                source_refs=source_refs,
                rule_refs=rule_refs,
            )

    async def _record_failure_event(self, run_id: str, step: str) -> None:
        async with self._session_factory.begin() as session:
            if await session.get(RunRecord, run_id) is None:
                raise KeyError(run_id)
            await self._append_event(
                session,
                run_id,
                step,
                EventStatus.FAILED,
                actor=ActorType.SYSTEM,
                error_code=ErrorCode.INTERNAL_ERROR,
            )

    async def _finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        result: dict[str, Any] | None = None,
        error_code: ErrorCode | str | None = None,
        decision_step: str,
        rule_refs: list[str],
    ) -> RunSnapshot:
        async with self._session_factory.begin() as session:
            run = await session.get(RunRecord, run_id, with_for_update=True)
            if run is None:
                raise KeyError(run_id)
            validate_transition(RunStatus(run.status), status)
            run.status = status.value
            run.result_json = result
            run.error_json = self._error(run, error_code) if error_code else None
            run.pending_gate_id = None
            run.updated_at = _now()
            if status == RunStatus.FAILED:
                event_status = EventStatus.FAILED
            elif error_code:
                event_status = EventStatus.BLOCKED
            else:
                event_status = EventStatus.SUCCEEDED
            await self._append_event(
                session,
                run_id,
                decision_step,
                event_status,
                actor=ActorType.RULE,
                rule_refs=rule_refs,
                error_code=error_code,
            )
            await self._append_event(
                session, run_id, "finalize", EventStatus.SUCCEEDED, actor=ActorType.SYSTEM
            )
        return await self.inspect(run_id)

    async def _create_gate(
        self,
        *,
        run_id: str,
        command_id: str,
        requested_by: str,
        proposal: SideEffectProposal,
    ) -> RunSnapshot:
        async with self._session_factory.begin() as session:
            run = await session.get(RunRecord, run_id, with_for_update=True)
            if run is None:
                raise KeyError(run_id)
            validate_transition(RunStatus(run.status), RunStatus.WAITING_HUMAN)
            now = _now()
            gate_id = str(uuid4())
            session.add(
                HumanGateRecord(
                    gate_id=gate_id,
                    run_id=run_id,
                    command_id=command_id,
                    reason=proposal.reason,
                    risk_level=proposal.risk_level.value,
                    requested_action=dict(proposal.payload),
                    status=GateStatus.PENDING.value,
                    requested_by=requested_by,
                    decided_by=None,
                    comment=None,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    decided_at=None,
                )
            )
            session.add(
                SideEffectCommandRecord(
                    command_id=command_id,
                    run_id=run_id,
                    step_id=proposal.step_id,
                    tool_name=proposal.tool_name,
                    idempotency_key=command_id,
                    risk_level=proposal.risk_level.value,
                    payload_ref=gate_id,
                    payload_json=self._command_envelope(proposal),
                    approval_ref=gate_id,
                    result_ref=None,
                    result_json=None,
                    status=CommandStatus.WAITING_APPROVAL.value,
                    created_at=now,
                    updated_at=now,
                )
            )
            run.status = RunStatus.WAITING_HUMAN.value
            run.pending_gate_id = gate_id
            run.updated_at = now
            await self._append_event(
                session,
                run_id,
                "create_human_gate",
                EventStatus.SUCCEEDED,
                actor=ActorType.SYSTEM,
                rule_refs=list(proposal.rule_refs),
            )
        return await self.inspect(run_id)

    async def _create_approved_command(
        self,
        *,
        run_id: str,
        command_id: str,
        proposal: SideEffectProposal,
    ) -> None:
        async with self._session_factory.begin() as session:
            run = await session.get(RunRecord, run_id, with_for_update=True)
            if run is None:
                raise KeyError(run_id)
            now = _now()
            session.add(
                SideEffectCommandRecord(
                    command_id=command_id,
                    run_id=run_id,
                    step_id=proposal.step_id,
                    tool_name=proposal.tool_name,
                    idempotency_key=command_id,
                    risk_level=proposal.risk_level.value,
                    payload_ref=command_id,
                    payload_json=self._command_envelope(proposal),
                    approval_ref=None,
                    result_ref=None,
                    result_json=None,
                    status=CommandStatus.APPROVED.value,
                    created_at=now,
                    updated_at=now,
                )
            )
            run.updated_at = now

    async def _execute_command(self, command_id: str) -> RunSnapshot:
        payload: dict[str, Any]
        rule_refs: list[str]
        uncertainty_rule_refs: list[str]
        run_id: str
        command_key: str
        tool_name: str
        reconcile_only = False
        async with self._session_factory.begin() as session:
            command = await session.get(SideEffectCommandRecord, command_id, with_for_update=True)
            if command is None:
                raise KeyError(command_id)
            run = await session.get(RunRecord, command.run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("command references missing Run")
            if run.status in {item.value for item in _TERMINAL_STATUSES}:
                return self._snapshot(run)
            if command.status == CommandStatus.SUCCEEDED.value:
                return self._snapshot(run)
            if command.status not in {
                CommandStatus.APPROVED.value,
                CommandStatus.EXECUTING.value,
                CommandStatus.UNKNOWN.value,
            }:
                raise RuntimeConflict("COMMAND_NOT_APPROVED")
            payload, rule_refs, uncertainty_rule_refs = self._command_parts(command.payload_json)
            run_id = command.run_id
            command_key = command.idempotency_key
            tool_name = command.tool_name
            reconcile_only = command.status in {
                CommandStatus.EXECUTING.value,
                CommandStatus.UNKNOWN.value,
            }
            if not reconcile_only:
                cas = cast(
                    CursorResult[Any],
                    await session.execute(
                        update(SideEffectCommandRecord)
                        .where(
                            SideEffectCommandRecord.command_id == command_id,
                            SideEffectCommandRecord.status == CommandStatus.APPROVED.value,
                        )
                        .values(status=CommandStatus.EXECUTING.value, updated_at=_now())
                    ),
                )
                if cas.rowcount != 1:
                    raise RuntimeConflict("COMMAND_CAS_CONFLICT")
                await self._append_event(
                    session,
                    run_id,
                    "execute_side_effect",
                    EventStatus.STARTED,
                    actor=ActorType.TOOL,
                    rule_refs=rule_refs,
                )

        try:
            adapter = self._adapters.get(command_id)
            if adapter is None:
                adapter = self._dependencies.write_tools.create(tool_name, payload)
                self._adapters[command_id] = adapter
            if reconcile_only:
                reconciled = await adapter.reconcile(idempotency_key=command_key)
                if reconciled is None:
                    return await self._mark_command_unknown(command_id, uncertainty_rule_refs)
                result = reconciled
            else:
                result = await adapter.execute(payload=payload, idempotency_key=command_key)
                if result.status == ToolResultStatus.UNKNOWN:
                    reconciled = await adapter.reconcile(idempotency_key=command_key)
                    if reconciled is not None:
                        result = reconciled
                if result.status == ToolResultStatus.SUCCEEDED:
                    self._side_effect_success_count += 1
        except ValueError as error:
            error_code = (
                ErrorCode.TOOL_DEFINITION_MISMATCH
                if str(error) == ErrorCode.TOOL_DEFINITION_MISMATCH.value
                else ErrorCode.TOOL_ADAPTER_ERROR
            )
            result = ToolResult(
                ok=False,
                status=ToolResultStatus.FAILED,
                data={},
                error_code=error_code,
            )
        except Exception:
            result = ToolResult(
                ok=False,
                status=ToolResultStatus.FAILED,
                data={},
                error_code=ErrorCode.TOOL_ADAPTER_ERROR,
            )
        return await self._store_command_result(
            command_id,
            result,
            rule_refs=rule_refs,
            uncertainty_rule_refs=uncertainty_rule_refs,
        )

    async def _mark_command_unknown(
        self, command_id: str, uncertainty_rule_refs: list[str] | None = None
    ) -> RunSnapshot:
        async with self._session_factory.begin() as session:
            command = await session.get(SideEffectCommandRecord, command_id, with_for_update=True)
            if command is None:
                raise KeyError(command_id)
            run = await session.get(RunRecord, command.run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("command references missing Run")
            command.status = CommandStatus.UNKNOWN.value
            command.updated_at = _now()
            self._set_run_error(run, RunStatus.BLOCKED, ErrorCode.SIDE_EFFECT_UNKNOWN)
            await self._append_event(
                session,
                run.run_id,
                "side_effect_reconcile_unknown",
                EventStatus.BLOCKED,
                actor=ActorType.TOOL,
                rule_refs=uncertainty_rule_refs or [],
                error_code=ErrorCode.SIDE_EFFECT_UNKNOWN,
            )
        return await self.inspect(run.run_id)

    async def _store_command_result(
        self,
        command_id: str,
        result: ToolResult,
        *,
        rule_refs: list[str],
        uncertainty_rule_refs: list[str],
    ) -> RunSnapshot:
        async with self._session_factory.begin() as session:
            command = await session.get(SideEffectCommandRecord, command_id, with_for_update=True)
            if command is None:
                raise KeyError(command_id)
            run = await session.get(RunRecord, command.run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("command references missing Run")
            now = _now()
            command.result_json = result.model_dump(mode="json")
            command.updated_at = now
            run.pending_gate_id = None
            run.updated_at = now
            error_code: ErrorCode | str | None
            if result.status == ToolResultStatus.SUCCEEDED:
                command.status = CommandStatus.SUCCEEDED.value
                run.status = RunStatus.SUCCEEDED.value
                run.result_json = result.data
                run.error_json = None
                event_status = EventStatus.SUCCEEDED
                error_code = None
                event_rule_refs = rule_refs
            elif result.status == ToolResultStatus.UNKNOWN:
                command.status = CommandStatus.UNKNOWN.value
                self._set_run_error(run, RunStatus.BLOCKED, ErrorCode.SIDE_EFFECT_UNKNOWN)
                event_status = EventStatus.BLOCKED
                error_code = ErrorCode.SIDE_EFFECT_UNKNOWN
                event_rule_refs = [*rule_refs, *uncertainty_rule_refs]
            else:
                command.status = CommandStatus.FAILED.value
                failure_code = result.error_code or ErrorCode.INTERNAL_ERROR
                self._set_run_error(run, RunStatus.FAILED, failure_code)
                event_status = EventStatus.FAILED
                error_code = failure_code
                event_rule_refs = rule_refs
            await self._append_event(
                session,
                run.run_id,
                "execute_side_effect",
                event_status,
                actor=ActorType.TOOL,
                rule_refs=event_rule_refs,
                error_code=error_code,
            )
            await self._append_event(
                session,
                run.run_id,
                "finalize",
                EventStatus.SUCCEEDED,
                actor=ActorType.SYSTEM,
            )
        return await self.inspect(run.run_id)

    @staticmethod
    def _command_envelope(proposal: SideEffectProposal) -> dict[str, Any]:
        return {
            "_gaia_command_envelope": 1,
            "payload": dict(proposal.payload),
            "rule_refs": list(proposal.rule_refs),
            "uncertainty_rule_refs": list(proposal.uncertainty_rule_refs),
        }

    @staticmethod
    def _command_parts(value: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
        """Read both M1 envelopes and legacy flat payloads from existing databases."""
        if value.get("_gaia_command_envelope") == 1:
            return (
                dict(value.get("payload", {})),
                list(value.get("rule_refs", [])),
                list(value.get("uncertainty_rule_refs", [])),
            )
        return dict(value), [], []

    @staticmethod
    async def _append_event(
        session: AsyncSession,
        run_id: str,
        step: str,
        status: EventStatus,
        *,
        actor: ActorType,
        source_refs: list[str] | None = None,
        rule_refs: list[str] | None = None,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        sequence = await session.scalar(
            update(RunRecord)
            .where(RunRecord.run_id == run_id)
            .values(event_sequence=RunRecord.event_sequence + 1)
            .returning(RunRecord.event_sequence)
        )
        if sequence is None:
            raise KeyError(run_id)
        session.add(
            RunEventRecord(
                event_id=str(uuid4()),
                run_id=run_id,
                sequence=sequence,
                timestamp=_now(),
                actor=actor.value,
                step=step,
                status=status.value,
                input_ref=None,
                output_ref=None,
                source_refs=source_refs or [],
                rule_refs=rule_refs or [],
                error_code=(PersistentRuntimeEngine._code(error_code) if error_code else None),
                details={},
            )
        )
        await session.flush()

    @staticmethod
    def _error(run: RunRecord, code: ErrorCode | str) -> dict[str, Any]:
        return operational_error(
            code,
            trace_id=run.trace_id,
        ).model_dump(mode="json")

    def _set_run_error(self, run: RunRecord, status: RunStatus, code: ErrorCode | str) -> None:
        run.status = status.value
        run.result_json = None
        run.error_json = self._error(run, code)
        run.pending_gate_id = None
        run.updated_at = _now()

    @staticmethod
    def _code(code: ErrorCode | str) -> str:
        return code.value if isinstance(code, ErrorCode) else code

    @staticmethod
    def _snapshot(record: RunRecord) -> RunSnapshot:
        return RunSnapshot(
            run_id=record.run_id,
            scenario_id=record.scenario_id,
            mode=RunMode(record.mode),
            status=RunStatus(record.status),
            user=UserIdentity.model_validate(record.user_json),
            version_bundle=VersionBundle.model_validate(record.version_bundle),
            result=record.result_json,
            error=ErrorResponse.model_validate(record.error_json) if record.error_json else None,
            pending_gate_id=record.pending_gate_id,
            created_at=_required_aware(record.created_at),
            updated_at=_required_aware(record.updated_at),
        )

    @staticmethod
    def _gate(record: HumanGateRecord) -> HumanGate:
        return HumanGate(
            gate_id=record.gate_id,
            run_id=record.run_id,
            command_id=record.command_id,
            reason=record.reason,
            risk_level=RiskLevel(record.risk_level),
            requested_action=record.requested_action,
            status=GateStatus(record.status),
            requested_by=record.requested_by,
            decided_by=record.decided_by,
            comment=record.comment,
            created_at=_required_aware(record.created_at),
            expires_at=_required_aware(record.expires_at),
            decided_at=_aware(record.decided_at),
        )

    @staticmethod
    def _event(record: RunEventRecord) -> RunEvent:
        return RunEvent(
            event_id=record.event_id,
            run_id=record.run_id,
            sequence=record.sequence,
            timestamp=_required_aware(record.timestamp),
            actor=ActorType(record.actor),
            step=record.step,
            status=EventStatus(record.status),
            input_ref=record.input_ref,
            output_ref=record.output_ref,
            source_refs=record.source_refs,
            rule_refs=record.rule_refs,
            error_code=record.error_code,
            details=record.details,
        )


_TERMINAL_STATUSES = {
    RunStatus.DEGRADED,
    RunStatus.BLOCKED,
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}
