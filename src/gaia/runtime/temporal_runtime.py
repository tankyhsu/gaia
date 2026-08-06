"""Temporal.io runtime migration adapter.

Gaia keeps the public runtime contract unchanged in `RuntimeEngine`, while the
migration path introduces a second execution branch that is intentionally explicit
about what has not been migrated yet. This module now defines the first-step
Temporal payload contract and keeps migration diagnostics machine-readable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import (
    ErrorCode,
    HumanGate,
    HumanGateDecisionRequest,
    RunEvent,
    RunPage,
    RunRequest,
    RunSnapshot,
    RunStatus,
    canonical_json,
)
from gaia.runtime.contracts import (
    RUN_LIST_DEFAULT_LIMIT,
    AuditProjection,
    RuntimeConflict,
    RuntimeEngine,
    RuntimePermissionDenied,
    RuntimeRunNotFound,
)
from gaia.runtime.dependencies import RuntimeDependencies
from gaia.runtime.safety import SafetyViolation, validate_run_admission


def _parse_server_address(address: str) -> tuple[str, int]:
    raw = address.strip()
    if not raw:
        raise ValueError("runtime.execution.server_address cannot be empty")

    if ":" not in raw:
        return raw, 7233

    if raw.startswith("[") and "]" in raw and raw.count("]") == 1:
        host = raw[1 : raw.index("]")]
        suffix = raw[raw.index("]") + 1 :]
        if not suffix:
            return host, 7233
        if not suffix.startswith(":"):
            raise ValueError(f"invalid server address {address!r}")
        try:
            return host, int(suffix[1:])
        except ValueError as error:
            raise ValueError(f"invalid port in server address {address!r}") from error

    parts = raw.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid server address {address!r}")
    host, port_text = parts
    if not host:
        raise ValueError(f"invalid server address {address!r}")
    try:
        return host, int(port_text)
    except ValueError as error:
        raise ValueError(f"invalid port in server address {address!r}") from error


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class TemporalRuntimeUnavailable(RuntimeError):
    """Raised when temporal runtime adapter is selected but not yet operational."""


TemporalBackend = Callable[[str, dict[str, object]], Awaitable[object]]


@dataclass(frozen=True)
class TemporalRuntimeEnvelope:
    """Structured message that migrates runtime intent into Temporal-ready input."""

    operation: str
    payload: dict[str, object]
    issued_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "issued_at": self.issued_at,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class TemporalRuntimePlan:
    """Execution plan fingerprint to keep adapter selection and runtime state traceable."""

    namespace: str
    task_queue: str
    server_address: str
    server_host: str
    server_port: int
    tls_enabled: bool
    task_timeout_seconds: int
    max_concurrent_workflows: int

    @classmethod
    def from_settings(cls, settings: RuntimeExecutionSettings) -> TemporalRuntimePlan:
        server_host, server_port = _parse_server_address(settings.server_address)
        return cls(
            namespace=settings.namespace,
            task_queue=settings.task_queue,
            server_address=settings.server_address,
            server_host=server_host,
            server_port=server_port,
            tls_enabled=settings.tls_enabled,
            task_timeout_seconds=settings.task_timeout_seconds,
            max_concurrent_workflows=settings.max_concurrent_workflows,
        )


class TemporalRuntimeEngine(RuntimeEngine):
    """Migration adapter for Temporal-backed execution.

    Behavior is intentionally explicit:
    - configuration is captured and exposed for observability/debug
    - operation envelopes are typed and deterministic for migration wiring
    - every public method raises a deterministic error until workflow mapping exists
    """

    def __init__(
        self,
        *,
        execution: RuntimeExecutionSettings | None = None,
        backend: TemporalBackend | None = None,
        dependencies: RuntimeDependencies | None = None,
        human_gate_ttl_seconds: int = 86400,
        temporal_interceptors: tuple[Any, ...] = (),
        audit_projection: AuditProjection | None = None,
        reason: str | None = None,
    ) -> None:
        settings = execution or RuntimeExecutionSettings(provider="temporal")
        self._plan = TemporalRuntimePlan.from_settings(settings)
        self._backend = backend
        self._dependencies = dependencies
        # One store, reachable two ways. The API reads and records decisions
        # through the engine; the Worker's Activities write and verify through
        # `dependencies`. If those were allowed to be different objects, an
        # approval could be recorded somewhere `execute_command` never looks --
        # a Run gated forever on a decision that was, in fact, made. Defaulting
        # to the dependencies' projection makes divergence take deliberate effort.
        self._audit_projection = audit_projection or (
            None if dependencies is None else dependencies.audit_projection
        )
        self._human_gate_ttl_seconds = human_gate_ttl_seconds
        self._temporal_interceptors = temporal_interceptors
        self._reason = (
            reason
            or "runtime.execution.provider=temporal is selected, but workflow "
            "mapping is not completed"
        )

    async def _dispatch(self, envelope: TemporalRuntimeEnvelope) -> object:
        if self._backend is None:
            self._not_ready_with_envelope(
                envelope.operation,
                envelope,
            )
        try:
            return await self._backend(envelope.operation, envelope.payload)
        except (RuntimeConflict, RuntimePermissionDenied, RuntimeRunNotFound):
            raise
        except Exception as error:
            raise TemporalRuntimeUnavailable(
                f"{self._reason}; runtime.operation={envelope.operation}; "
                f"backend failed for operation {envelope.operation}: {error}"
            ) from error

    @staticmethod
    def _as_dict(value: object, operation: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
        raise TemporalRuntimeUnavailable(f"{operation}: backend must return dict payload")

    @staticmethod
    def _as_list_dict(value: object, operation: str) -> list[dict[str, Any]]:
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return cast(list[dict[str, Any]], value)
        raise TemporalRuntimeUnavailable(f"{operation}: backend must return list[dict] payload")

    def _not_ready_with_envelope(
        self,
        operation: str,
        envelope: TemporalRuntimeEnvelope,
    ) -> NoReturn:
        raise TemporalRuntimeUnavailable(
            f"{self._reason}; runtime.operation={operation}; "
            f"migration.envelope={envelope.to_dict()}; "
            f"temporal.namespace={self._plan.namespace!r}; "
            f"temporal.task_queue={self._plan.task_queue!r}; "
            f"temporal.server={self._plan.server_address!r}; "
            f"temporal.host={self._plan.server_host!r}; "
            f"temporal.port={self._plan.server_port}; "
            f"temporal.tls_enabled={self._plan.tls_enabled!r}"
        )

    def _not_ready(self, operation: str) -> NoReturn:
        raise TemporalRuntimeUnavailable(
            f"{self._reason}; runtime.operation={operation}; "
            f"temporal.namespace={self._plan.namespace!r}; "
            f"temporal.task_queue={self._plan.task_queue!r}; "
            f"temporal.server={self._plan.server_address!r}; "
            f"temporal.host={self._plan.server_host!r}; "
            f"temporal.port={self._plan.server_port}; "
            f"temporal.tls_enabled={self._plan.tls_enabled!r}"
        )

    @property
    def plan(self) -> TemporalRuntimePlan:
        return self._plan

    @property
    def temporal_interceptors(self) -> tuple[Any, ...]:
        return self._temporal_interceptors

    def activity_handlers(self) -> tuple[Callable[..., object], ...]:
        """Return application-bound Activity handlers for a separate Worker."""

        if self._dependencies is None:
            return ()
        from gaia.runtime.temporal_activity import TemporalRuntimeActivities

        activities = TemporalRuntimeActivities(self._dependencies)
        return (
            activities.run_scenario,
            activities.execute_command,
            activities.record_audit,
        )

    def build_create_envelope(
        self, request: RunRequest, idempotency_key: str
    ) -> TemporalRuntimeEnvelope:
        request_payload = request.model_dump(mode="json")
        issued_at = _utcnow_iso()
        return TemporalRuntimeEnvelope(
            operation="create",
            issued_at=issued_at,
            payload={
                "request": request_payload,
                "idempotency_key": idempotency_key,
                "request_fingerprint": canonical_json(request_payload),
                "issued_at": issued_at,
            },
        )

    def build_decide_envelope(
        self,
        gate_id: str,
        body: HumanGateDecisionRequest,
    ) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="decide",
            issued_at=_utcnow_iso(),
            payload={
                "gate_id": gate_id,
                "decision": body.decision.value,
                "decided_by": body.decided_by,
                "roles": tuple(body.roles),
                "comment": body.comment,
            },
        )

    def build_cancel_envelope(self, run_id: str, reason: str) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="cancel",
            issued_at=_utcnow_iso(),
            payload={"run_id": run_id, "reason": reason},
        )

    def build_inspect_envelope(self, run_id: str) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="inspect",
            issued_at=_utcnow_iso(),
            payload={"run_id": run_id},
        )

    def build_list_runs_envelope(
        self,
        *,
        organization: str | None,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="list_runs",
            issued_at=_utcnow_iso(),
            payload={
                "organization": organization,
                "status": status.value if status is not None else None,
                "scenario_id": scenario_id,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def build_events_after_envelope(
        self, run_id: str, sequence: int = 0
    ) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="events_after",
            issued_at=_utcnow_iso(),
            payload={"run_id": run_id, "sequence": sequence},
        )

    def build_get_gate_envelope(self, gate_id: str) -> TemporalRuntimeEnvelope:
        return TemporalRuntimeEnvelope(
            operation="get_gate",
            issued_at=_utcnow_iso(),
            payload={"gate_id": gate_id},
        )

    async def create(self, request: RunRequest, idempotency_key: str) -> RunSnapshot:
        envelope = self.build_create_envelope(request, idempotency_key)
        if self._dependencies is not None:
            try:
                runner = self._dependencies.runner_for(request.scenario_id)
            except KeyError as error:
                raise RuntimeConflict("SCENARIO_NOT_FOUND") from error
            try:
                validate_run_admission(
                    configured_environment=self._dependencies.environment,
                    request=request,
                    policy=runner.execution_policy,
                )
            except SafetyViolation as error:
                raise RuntimePermissionDenied(error.code.value) from error
            version_bundle = await self._dependencies.version_resolver.resolve(
                request,
                runner.version_bundle,
            )
            envelope.payload["version_bundle"] = version_bundle.model_dump(mode="json")
            envelope.payload["human_gate_ttl_seconds"] = self._human_gate_ttl_seconds
        payload = self._as_dict(await self._dispatch(envelope), "create")
        return RunSnapshot.model_validate(payload)

    async def decide(
        self,
        gate_id: str,
        body: HumanGateDecisionRequest,
    ) -> RunSnapshot:
        """Record the decision as authenticated evidence, then tell Temporal.

        Order matters. The projection write happens first because it is the
        record `execute_command` consults before performing the write, and it is
        the one store a Temporal client cannot reach. Signalling Temporal first
        would leave a window in which the Workflow believes it is approved while
        Gaia holds no authenticated approval -- and the Activity would refuse
        the write, stranding the Run.
        """

        if self._audit_projection is not None:
            # Read the gate from Temporal first and hand the document over, so a
            # decision made before the Workflow's own projection landed still
            # records. The projection trails the Workflow by one Activity, and
            # an approver is entitled to act the moment they can see the gate.
            gate = await self.get_gate(gate_id)
            authorized = await self._audit_projection.record_decision(
                gate=gate.model_dump(mode="json"),
                decision=body.decision.value,
                decided_by=body.decided_by,
                comment=body.comment,
                decided_at=datetime.now(UTC),
            )
            if not authorized:
                raise RuntimeConflict(ErrorCode.GATE_NOT_PENDING.value)
        envelope = self.build_decide_envelope(gate_id=gate_id, body=body)
        payload = self._as_dict(await self._dispatch(envelope), "decide")
        return RunSnapshot.model_validate(payload)

    async def cancel(self, run_id: str, reason: str) -> RunSnapshot:
        envelope = self.build_cancel_envelope(run_id, reason)
        payload = self._as_dict(await self._dispatch(envelope), "cancel")
        return RunSnapshot.model_validate(payload)

    async def _audit_fallback(
        self,
        error: Exception,
        lookup: Callable[[AuditProjection], Awaitable[Any]],
    ) -> Any:
        """Answer a read from durable evidence when Temporal cannot answer it.

        Temporal is authoritative while a Run is still replayable. Once its
        namespace retention closes -- or if its Workers are down -- the Workflow
        can no longer be queried, and that must not be the same thing as the Run
        never having happened. If the projection has no record either, the
        original Temporal failure is what the caller sees, because then the
        answer really is unknown rather than merely archived.
        """

        if self._audit_projection is None:
            raise error
        record = await lookup(self._audit_projection)
        if record is None:
            raise error
        return record

    async def inspect(self, run_id: str) -> RunSnapshot:
        envelope = self.build_inspect_envelope(run_id)
        try:
            payload = self._as_dict(await self._dispatch(envelope), "inspect")
        except (RuntimeRunNotFound, TemporalRuntimeUnavailable) as error:
            payload = await self._audit_fallback(
                error,
                lambda projection: projection.get_run(run_id),
            )
        return RunSnapshot.model_validate(payload)

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = RUN_LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> RunPage:
        """List Runs from Gaia's durable evidence store, never from Visibility.

        Listing used to walk Temporal Visibility and then issue one Workflow
        Query per row to recover each snapshot -- `limit` history replays for a
        single page, unavailable whenever the Workers were down, and empty for
        anything past the retention window. The projection holds the same
        snapshots, indexed for exactly this query.
        """

        if self._audit_projection is None:
            self._not_ready_with_envelope(
                "list_runs",
                self.build_list_runs_envelope(
                    organization=organization,
                    status=status,
                    scenario_id=scenario_id,
                    limit=limit,
                    cursor=cursor,
                ),
            )
        page = await self._audit_projection.list_runs(
            organization=organization,
            status=status.value if status is not None else None,
            scenario_id=scenario_id,
            limit=limit,
            cursor=cursor,
        )
        return RunPage.model_validate(page)

    async def events_after(self, run_id: str, sequence: int = 0) -> list[RunEvent]:
        envelope = self.build_events_after_envelope(run_id=run_id, sequence=sequence)
        try:
            events = self._as_list_dict(await self._dispatch(envelope), "events_after")
        except (RuntimeRunNotFound, TemporalRuntimeUnavailable) as error:
            events = await self._audit_fallback(
                error,
                lambda projection: projection.events_after(run_id, sequence),
            )
        return [RunEvent.model_validate(item) for item in events]

    async def get_gate(self, gate_id: str) -> HumanGate:
        envelope = self.build_get_gate_envelope(gate_id)
        try:
            payload = self._as_dict(await self._dispatch(envelope), "get_gate")
        except (RuntimeRunNotFound, TemporalRuntimeUnavailable) as error:
            payload = await self._audit_fallback(
                error,
                lambda projection: projection.get_gate(gate_id),
            )
        return HumanGate.model_validate(payload)

    async def gates_for_run(self, run_id: str) -> list[HumanGate]:
        """Read every gate `run_id` opened from Gaia's durable evidence store.

        Like `list_runs`, this never dispatches to Temporal: Temporal Workflow
        History only ever exposes the *current* gate (via `get_gate`'s Query),
        not the full set a Run opened over its lifetime, and it is deleted
        once namespace retention closes regardless. The audit projection is
        the only store that answers this at all.
        """

        if self._audit_projection is None:
            self._not_ready("gates_for_run")
        gates = await self._audit_projection.gates_for_run(run_id)
        return [HumanGate.model_validate(gate) for gate in gates]
