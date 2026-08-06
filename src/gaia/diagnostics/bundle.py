"""Redacted diagnostic bundle projected from the active Runtime."""

from __future__ import annotations

import hashlib
from typing import Any

from gaia.contracts.models import HumanGate, RunEvent
from gaia.runtime.contracts import RuntimeEngine


class DiagnosticExporter:
    """Export read-only Run evidence without owning a second execution store."""

    def __init__(self, runtime: RuntimeEngine) -> None:
        self._runtime = runtime

    async def export(self, run_id: str) -> dict[str, Any]:
        run = await self._runtime.inspect(run_id)
        events = await self._runtime.events_after(run_id)
        gates = await self._gates(run.pending_gate_id, events)
        user = run.user.model_dump(mode="json")
        user["id"] = _pseudonym(str(user["id"]))
        return {
            "schema_version": "2.0.0",
            "run": {
                "run_id": run.run_id,
                "scenario_id": run.scenario_id,
                "mode": run.mode.value,
                "status": run.status.value,
                "user": user,
                "version_bundle": run.version_bundle.model_dump(mode="json"),
                "pending_result": run.pending_result,
                "action_plan": (
                    run.action_plan.model_dump(mode="json")
                    if run.action_plan is not None
                    else None
                ),
                "result": run.result,
                "error": run.error.model_dump(mode="json") if run.error is not None else None,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
            },
            "events": [_event(item) for item in events],
            "human_gates": [_gate(item) for item in gates],
            "execution_evidence": {
                "owner": "temporal",
                "command_source": "workflow_history",
            },
            "redaction": {
                "user_id": "sha256 pseudonym",
                "request_text": "omitted",
                "secrets": "omitted",
            },
        }

    async def _gates(
        self,
        pending_gate_id: str | None,
        events: list[RunEvent],
    ) -> list[HumanGate]:
        gate_ids = {
            gate_id
            for gate_id in (
                pending_gate_id,
                *(
                    event.details.get("gate_id")
                    for event in events
                    if isinstance(event.details.get("gate_id"), str)
                ),
            )
            if gate_id is not None
        }
        gates: list[HumanGate] = []
        for gate_id in sorted(gate_ids):
            try:
                gates.append(await self._runtime.get_gate(gate_id))
            except KeyError:
                continue
        return gates


def _event(item: RunEvent) -> dict[str, Any]:
    return {
        "sequence": item.sequence,
        "timestamp": item.timestamp.isoformat(),
        "actor": item.actor.value,
        "step": item.step,
        "status": item.status.value,
        "source_refs": item.source_refs,
        "rule_refs": item.rule_refs,
        "error_code": item.error_code,
        "details": item.details,
    }


def _gate(item: HumanGate) -> dict[str, Any]:
    return {
        "gate_id": item.gate_id,
        "command_id": item.command_id,
        "status": item.status.value,
        "risk_level": item.risk_level.value,
        "approval_view": (
            item.approval_view.model_dump(mode="json")
            if item.approval_view is not None
            else None
        ),
        "decided": item.decided_at is not None,
    }


def _pseudonym(value: str) -> str:
    return "user_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
