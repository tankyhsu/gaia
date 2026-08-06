"""Durable Temporal Workflow for Gaia runtime state.

This first replacement slice intentionally owns only durable run identity,
initial state, event history, queries, and state/cancel signals. LangGraph
execution and HumanGate/tool activities are added in subsequent slices.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from gaia.runtime.temporal_names import (
    GAIA_AUDIT_ACTIVITY,
    GAIA_COMMAND_ACTIVITY,
    GAIA_RUNTIME_WORKFLOW,
    GAIA_SCENARIO_ACTIVITY,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)

TERMINAL_STATUSES = {"blocked", "cancelled", "degraded", "failed", "succeeded"}

# Evidence is not allowed to be best-effort. A transient projection failure is
# retried without limit rather than dropped, so a Run cannot reach a terminal
# state whose only surviving record is Temporal Workflow History -- which the
# namespace retention window deletes on a schedule.
AUDIT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=0,
    maximum_interval=timedelta(seconds=60),
)
AUDIT_TIMEOUT = timedelta(seconds=30)


def build_initial_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the public Gaia snapshot stored in Temporal Workflow history."""

    request = payload["request"]
    return {
        "run_id": payload["run_id"],
        "scenario_id": request["scenario_id"],
        "mode": request["mode"],
        "status": "received",
        "user": request["user"],
        "version_bundle": payload["version_bundle"],
        "created_at": payload["issued_at"],
        "updated_at": payload["issued_at"],
    }


def _event(
    *,
    run_id: str,
    sequence: int,
    timestamp: str,
    step: str,
    status: str,
    actor: str = "system",
    source_refs: list[str] | None = None,
    rule_refs: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"{run_id}:{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "timestamp": timestamp,
        "actor": actor,
        "step": step,
        "status": status,
        "source_refs": source_refs or [],
        "rule_refs": rule_refs or [],
        "details": details or {},
    }


def apply_outcome_to_snapshot(
    snapshot: dict[str, Any],
    outcome: dict[str, Any],
    *,
    timestamp: str,
) -> dict[str, Any]:
    """Apply one terminal Activity result to the durable public snapshot."""

    updated = dict(snapshot)
    updated["status"] = outcome["status"]
    updated["result"] = outcome.get("result")
    updated["updated_at"] = timestamp
    if outcome.get("trace_id") is not None:
        updated["trace_id"] = outcome["trace_id"]
    error_code = outcome.get("error_code")
    if error_code is not None:
        updated["error"] = {
            "code": error_code,
            "message": str(error_code),
            "trace_id": updated["run_id"],
            "category": "unknown",
            "retryable": False,
            "operator_action": "Inspect the Temporal Workflow and Gaia trace.",
            "details": {},
        }
    return updated


def command_maximum_attempts(proposal: dict[str, Any]) -> int:
    """Map a Gaia write contract to Temporal Activity retry ownership."""

    if proposal["recovery_strategy"] == "at_most_once_manual":
        return 1
    return int(proposal["max_retries"]) + 1


def command_result_outcome(
    result: dict[str, Any],
    *,
    recovery_strategy: str,
) -> dict[str, Any]:
    """Normalize an Activity result without creating a second Command store."""

    if result["status"] == "succeeded":
        return {
            "status": "succeeded",
            "result": result["data"],
            "error_code": None,
        }
    error_code = result.get("error_code")
    if result["status"] == "unknown":
        error_code = "SIDE_EFFECT_UNKNOWN"
    return {
        "status": (
            "blocked"
            if error_code
            in {
                "GUARDRAIL_BLOCKED",
                "SIDE_EFFECT_UNKNOWN",
                # A write refused for want of a verifiable approval was denied,
                # not attempted and broken. `failed` would invite a retry.
                "GATE_DECISION_UNVERIFIED",
            }
            or recovery_strategy == "at_most_once_manual"
            else "failed"
        ),
        "result": None,
        "error_code": error_code or "TOOL_ADAPTER_ERROR",
    }


def command_result_rule_refs(
    proposal: dict[str, Any],
    outcome: dict[str, Any],
) -> list[str]:
    """Attribute uncertainty rules only when command outcome is unknown."""

    if outcome.get("error_code") != "SIDE_EFFECT_UNKNOWN":
        return []
    return list(proposal.get("uncertainty_rule_refs", []))


def reserve_budget_step(budget: dict[str, Any]) -> bool:
    """Reserve one Workflow-owned step before scheduling a Command Activity."""

    if not budget:
        return True
    used = int(budget.get("steps_used", 0))
    maximum = int(budget.get("max_steps", 0))
    if used >= maximum:
        return False
    budget["steps_used"] = used + 1
    return True


@workflow.defn(name=GAIA_RUNTIME_WORKFLOW)
class GaiaRuntimeWorkflow:
    """Temporal-owned durable state for one Gaia Run.

    **This class is replay-critical code.** Temporal resumes a Run by replaying
    its recorded history against whatever version of this class the Worker is
    running. Changing the order, count, or condition of the Activity calls,
    timers, and signals below changes the decisions replay expects, and an
    in-flight Run whose history no longer matches cannot advance -- including a
    Run parked on a HumanGate, which cannot then be approved or rejected.

    Two things keep that from being a landmine, and both must stay in place:

    * `tests/integration/test_workflow_replay.py` replays recorded histories
      against this code, so an incompatible edit fails in CI rather than in
      production.
    * Setting `runtime.execution.deployment_name` and `build_id` starts the
      Worker under pinned deployment versioning, which keeps every in-flight Run
      on the Worker build it started on, so a rollout only moves *new* Runs onto
      new code. Pinning is declared on the Worker rather than here on purpose --
      declaring it on the Workflow makes a Worker that has no deployment
      configured stop accepting Workflow tasks entirely. Without it, every
      Worker serves every Run, and that is the configuration in which an
      incompatible edit does break Runs already in flight.

    Business rules belong in Activities, which are free to change: only the
    orchestration skeleton is pinned.
    """

    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        # Every gate this Run has opened, not just the one it waits on now. A
        # Run that clears `pending_gate_id` on completion must still be able to
        # answer "who approved this" -- keeping only the current gate is how the
        # evidence view came to report an approved Run as never approved.
        self._gates: list[dict[str, Any]] = []
        self._request_fingerprint = ""
        self._budget: dict[str, Any] = {}
        self._flushed_sequence = 0
        self._flushed_at: str | None = None

    @property
    def _pending_gate(self) -> dict[str, Any] | None:
        for gate in reversed(self._gates):
            if gate["status"] == "pending":
                return gate
        return None

    async def _flush(self) -> None:
        """Project new evidence into Gaia's durable audit store.

        Called at every point where the Run's evidence changes meaningfully --
        not once at the end -- so a Run that is waiting on a human, stuck, or
        killed mid-flight is still answerable from Gaia's own database.
        """

        pending = [
            dict(event)
            for event in self._events
            if event["sequence"] > self._flushed_sequence
        ]
        updated_at = self._snapshot.get("updated_at")
        if not pending and updated_at == self._flushed_at:
            return
        await workflow.execute_activity(
            GAIA_AUDIT_ACTIVITY,
            {
                "snapshot": dict(self._snapshot),
                "events": pending,
                "gates": [dict(gate) for gate in self._gates],
            },
            start_to_close_timeout=AUDIT_TIMEOUT,
            retry_policy=AUDIT_RETRY_POLICY,
        )
        if self._events:
            self._flushed_sequence = self._events[-1]["sequence"]
        self._flushed_at = updated_at

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._execute(payload)
        finally:
            # A Run whose evidence could not be recorded is not a completed Run.
            # Letting this failure replace the return value is deliberate: it is
            # louder than a silent gap in the audit trail.
            await self._flush()

    async def _execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._request_fingerprint = payload["request_fingerprint"]
        self._snapshot = build_initial_snapshot(payload)
        self._events = [
            _event(
                run_id=self._snapshot["run_id"],
                sequence=1,
                timestamp=self._snapshot["created_at"],
                step="receive_request",
                status="succeeded",
            )
        ]
        self._record_transition("validated", "validate_request")
        self._record_transition("running", "start_workflow")
        # Project admission before the first Activity runs: a Run that hangs or
        # is killed inside its scenario still has to be answerable from Gaia.
        await self._flush()
        activity_input: dict[str, Any] = {
            "run_id": self._snapshot["run_id"],
            "request": payload["request"],
            "budget": self._budget,
        }
        while True:
            try:
                outcome = await workflow.execute_activity(
                    GAIA_SCENARIO_ACTIVITY,
                    activity_input,
                    result_type=dict,
                    start_to_close_timeout=timedelta(
                        seconds=payload["activity_timeout_seconds"]
                    ),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                if self._snapshot["status"] != "cancelled":
                    self._snapshot = apply_outcome_to_snapshot(
                        self._snapshot,
                        {
                            "status": "failed",
                            "result": None,
                            "error_code": "INTERNAL_ERROR",
                        },
                        timestamp=workflow.now().isoformat(),
                    )
                    self._upsert_status(self._snapshot["status"])
                    self._append_event(
                        step="run_scenario_activity",
                        status="failed",
                        details={"error_code": "INTERNAL_ERROR"},
                    )
                return dict(self._snapshot)

            if self._snapshot["status"] == "cancelled":
                return dict(self._snapshot)
            activity_budget = outcome.get("budget")
            if isinstance(activity_budget, dict):
                self._budget = dict(activity_budget)
            self._append_outcome_trace(outcome)
            await self._flush()
            handoff = outcome.get("handoff")
            if handoff is not None:
                activity_input = {
                    "run_id": self._snapshot["run_id"],
                    "request": payload["request"],
                    "handoff": handoff,
                    "budget": self._budget,
                }
                self._append_event(
                    step="agent_handoff",
                    status="succeeded",
                    details={
                        "target_agent": handoff["current_agent"],
                        "handoff_count": handoff["handoff_count"],
                    },
                )
                continue
            if outcome.get("side_effect") is not None:
                command_result = await self._handle_side_effect(outcome, payload)
                continuation = outcome.get("continuation")
                if command_result is None or continuation is None:
                    return dict(self._snapshot)
                activity_input = {
                    "run_id": self._snapshot["run_id"],
                    "request": payload["request"],
                    "continuation": {
                        **continuation,
                        "action_result": command_result.get("result") or {},
                    },
                    "budget": self._budget,
                }
                self._append_event(
                    step="resume_continuation",
                    status="succeeded",
                    details={"handler": continuation["handler"]},
                )
                continue
            self._snapshot = apply_outcome_to_snapshot(
                self._snapshot,
                outcome,
                timestamp=workflow.now().isoformat(),
            )
            self._upsert_status(self._snapshot["status"])
            self._append_event(
                step=outcome["decision_step"],
                status={
                    "blocked": "blocked",
                    "failed": "failed",
                }.get(outcome["status"], "succeeded"),
                rule_refs=outcome["decision_rule_refs"],
            )
            self._append_event(step="finalize", status="succeeded")
            return dict(self._snapshot)

    async def _handle_side_effect(
        self,
        outcome: dict[str, Any],
        workflow_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposal = outcome["side_effect"]
        if not proposal["requires_approval"]:
            return await self._finish_side_effect(outcome, proposal)

        created_at = workflow.now()
        run_id = self._snapshot["run_id"]
        gate_id = f"{run_id}:gate:{proposal['step_id']}"
        gate = {
            "gate_id": gate_id,
            "run_id": run_id,
            "command_id": f"{run_id}:command:{proposal['step_id']}",
            "reason": proposal["reason"],
            "risk_level": proposal["risk_level"],
            "requested_action": proposal["payload"],
            "approval_view": proposal["approval_view"],
            "status": "pending",
            "requested_by": workflow_input["request"]["user"]["id"],
            "decided_by": None,
            "comment": None,
            "created_at": created_at.isoformat(),
            "expires_at": (
                created_at
                + timedelta(seconds=workflow_input["human_gate_ttl_seconds"])
            ).isoformat(),
            "decided_at": None,
        }
        self._gates.append(gate)
        self._snapshot["status"] = "waiting_human"
        self._upsert_status("waiting_human")
        self._snapshot["pending_gate_id"] = gate_id
        self._snapshot["pending_result"] = outcome.get("pending_result")
        self._snapshot["updated_at"] = created_at.isoformat()
        self._append_event(
            step="create_human_gate",
            status="succeeded",
            rule_refs=proposal.get("rule_refs", []),
            details={"gate_id": gate_id, "tool_name": proposal["tool_name"]},
        )
        # Record the pending gate before blocking on it. A Run can wait here for
        # the whole TTL; the approval request has to be visible in Gaia for all
        # of it, not only once somebody decides.
        await self._flush()
        try:
            await workflow.wait_condition(
                lambda: gate["status"] != "pending"
                or self._snapshot["status"] == "cancelled",
                timeout=timedelta(
                    seconds=workflow_input["human_gate_ttl_seconds"]
                ),
            )
        except TimeoutError:
            self._expire_gate(gate)
            return None

        # The decision itself arrives through the `decide` Update, which cannot
        # await. This is the first point after it where the Workflow can record
        # who decided what.
        await self._flush()
        if self._snapshot["status"] == "cancelled":
            return None
        if gate["status"] == "rejected":
            return None
        return await self._finish_side_effect(outcome, proposal, gate_id=gate_id)

    async def _finish_side_effect(
        self,
        outcome: dict[str, Any],
        proposal: dict[str, Any],
        *,
        gate_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = await self._execute_command(proposal, gate_id=gate_id)
        if (
            normalized["status"] == "succeeded"
            and outcome.get("continuation") is not None
        ):
            return normalized
        if (
            normalized["status"] == "succeeded"
            and outcome.get("pending_result") is not None
        ):
            normalized["result"] = outcome["pending_result"]
        self._snapshot = apply_outcome_to_snapshot(
            self._snapshot,
            normalized,
            timestamp=workflow.now().isoformat(),
        )
        self._upsert_status(self._snapshot["status"])
        self._append_event(
            step="finalize",
            status={
                "blocked": "blocked",
                "failed": "failed",
            }.get(normalized["status"], "succeeded"),
        )
        return None

    async def _execute_command(
        self,
        proposal: dict[str, Any],
        *,
        gate_id: str | None = None,
    ) -> dict[str, Any]:
        if not reserve_budget_step(self._budget):
            self._append_event(
                step="enforce_budget",
                status="blocked",
                details={"kind": "step"},
            )
            return {
                "status": "blocked",
                "result": None,
                "error_code": "BUDGET_EXCEEDED",
            }
        run_id = self._snapshot["run_id"]
        command_id = f"{run_id}:command:{proposal['step_id']}"
        self._snapshot["status"] = "running"
        self._upsert_status("running")
        self._snapshot["updated_at"] = workflow.now().isoformat()
        self._append_event(
            step="execute_side_effect",
            status="succeeded",
            rule_refs=proposal.get("rule_refs", []),
            details={
                "command_id": command_id,
                "tool_name": proposal["tool_name"],
            },
        )
        try:
            result = await workflow.execute_activity(
                GAIA_COMMAND_ACTIVITY,
                {
                    "run_id": run_id,
                    "scenario_id": self._snapshot["scenario_id"],
                    "command_id": command_id,
                    "proposal": proposal,
                    # The Activity re-checks the approval against Gaia's own
                    # store; the Workflow's word is not enough to authorize a
                    # write, because the Workflow accepts Updates from anyone
                    # who can reach the Temporal namespace.
                    "requires_approval": bool(proposal["requires_approval"]),
                    "gate_id": gate_id,
                },
                result_type=dict,
                start_to_close_timeout=timedelta(
                    seconds=int(proposal["timeout_seconds"])
                ),
                retry_policy=RetryPolicy(
                    maximum_attempts=command_maximum_attempts(proposal)
                ),
            )
            normalized = command_result_outcome(
                result,
                recovery_strategy=proposal["recovery_strategy"],
            )
            normalized["trace_id"] = result.get("trace_id")
        except Exception:
            if self._snapshot["status"] == "cancelled":
                return {
                    "status": "cancelled",
                    "result": None,
                    "error_code": None,
                }
            uncertain = proposal["recovery_strategy"] in {
                "reconcilable",
                "at_most_once_manual",
            }
            normalized = {
                "status": "blocked" if uncertain else "failed",
                "result": None,
                "error_code": (
                    "SIDE_EFFECT_UNKNOWN" if uncertain else "TOOL_ADAPTER_ERROR"
                ),
            }

        self._append_event(
            step="command_result",
            status={
                "blocked": "blocked",
                "failed": "failed",
            }.get(normalized["status"], "succeeded"),
            rule_refs=command_result_rule_refs(proposal, normalized),
            details={
                "command_id": command_id,
                "tool_name": proposal["tool_name"],
                "error_code": normalized.get("error_code"),
            },
        )
        return normalized

    def _expire_gate(self, gate: dict[str, Any]) -> None:
        if gate["status"] != "pending":
            return
        timestamp = workflow.now().isoformat()
        gate["status"] = "expired"
        gate["decided_at"] = timestamp
        self._snapshot = apply_outcome_to_snapshot(
            self._snapshot,
            {
                "status": "blocked",
                "result": None,
                "error_code": "HUMAN_GATE_EXPIRED",
            },
            timestamp=timestamp,
        )
        self._upsert_status(self._snapshot["status"])
        self._snapshot["pending_gate_id"] = None
        self._append_event(
            step="human_gate_expired",
            status="blocked",
            details={"gate_id": gate["gate_id"]},
        )

    def _append_event(
        self,
        *,
        step: str,
        status: str,
        actor: str = "system",
        source_refs: list[str] | None = None,
        rule_refs: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._events.append(
            _event(
                run_id=self._snapshot["run_id"],
                sequence=len(self._events) + 1,
                timestamp=self._snapshot["updated_at"],
                step=step,
                status=status,
                actor=actor,
                source_refs=source_refs,
                rule_refs=rule_refs,
                details=details,
            )
        )

    def _append_outcome_trace(self, outcome: dict[str, Any]) -> None:
        for item in outcome.get("trace", []):
            self._append_event(
                step=item["name"],
                status="succeeded",
                actor=item["actor"],
                source_refs=item.get("source_refs", []),
                rule_refs=item.get("rule_refs", []),
            )

    def _record_transition(self, status: str, step: str) -> None:
        timestamp = workflow.now().isoformat()
        self._snapshot["status"] = status
        self._upsert_status(status)
        self._snapshot["updated_at"] = timestamp
        self._append_event(step=step, status="succeeded")

    @workflow.query(name="snapshot")
    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    @workflow.query(name="request_fingerprint")
    def request_fingerprint(self) -> str:
        return self._request_fingerprint

    @workflow.query(name="events_after")
    def events_after(self, sequence: int = 0) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events if event["sequence"] > sequence]

    @workflow.query(name="gate")
    def gate(self, gate_id: str) -> dict[str, Any] | None:
        for gate in self._gates:
            if gate["gate_id"] == gate_id:
                return dict(gate)
        return None

    @workflow.query(name="gates")
    def gates(self) -> list[dict[str, Any]]:
        return [dict(gate) for gate in self._gates]

    @workflow.update(name="decide")
    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        gate = next(
            (item for item in self._gates if item["gate_id"] == payload["gate_id"]),
            None,
        )
        if gate is None:
            raise ValueError("GATE_NOT_FOUND")
        if "approver" not in payload["roles"]:
            raise ValueError("FORBIDDEN")
        if gate["status"] != "pending":
            return dict(self._snapshot)

        timestamp = workflow.now().isoformat()
        decision = payload["decision"]
        gate["status"] = decision
        gate["decided_by"] = payload["decided_by"]
        gate["comment"] = payload["comment"]
        gate["decided_at"] = timestamp
        self._snapshot["pending_gate_id"] = None
        self._snapshot["updated_at"] = timestamp
        if decision == "rejected":
            self._snapshot = apply_outcome_to_snapshot(
                self._snapshot,
                {
                    "status": "blocked",
                    "result": None,
                    "error_code": "HUMAN_GATE_REJECTED",
                },
                timestamp=timestamp,
            )
            self._upsert_status(self._snapshot["status"])
            self._append_event(
                step="human_gate_rejected",
                status="blocked",
                details={"gate_id": gate["gate_id"]},
            )
        else:
            self._snapshot["status"] = "running"
            self._upsert_status("running")
            self._append_event(
                step="human_gate_approved",
                status="succeeded",
                details={"gate_id": gate["gate_id"]},
            )
        return dict(self._snapshot)

    @workflow.signal(name="cancel")
    def cancel(self, payload: dict[str, Any]) -> None:
        timestamp = workflow.now().isoformat()
        self._snapshot["status"] = "cancelled"
        self._upsert_status("cancelled")
        self._snapshot["updated_at"] = timestamp
        self._append_event(
            step="cancel_run",
            status="succeeded",
            details={"reason": payload["reason"]},
        )

    @staticmethod
    def _upsert_status(status: str) -> None:
        workflow.upsert_search_attributes(
            [GAIA_STATUS_SEARCH_ATTRIBUTE.value_set(status)]
        )
