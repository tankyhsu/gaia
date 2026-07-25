"""Runtime-owned side-effect command state and adapter execution protocol."""

from __future__ import annotations

import hashlib
from typing import Any

from gaia.contracts.models import CommandStatus, ToolResult, ToolResultStatus, canonical_json
from gaia.sdk.tool import WriteAdapter


class CommandNotApproved(ValueError):
    pass


def command_idempotency_key(
    *,
    scenario_id: str,
    workflow_version: str,
    run_id: str,
    step_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> str:
    material = "+".join(
        [scenario_id, workflow_version, run_id, step_id, tool_name, canonical_json(payload)]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SideEffectExecutor:
    """In-memory command executor; persistence CAS is performed by Engine in T08."""

    def __init__(self, adapter: WriteAdapter) -> None:
        self._adapter = adapter
        self._status: dict[str, CommandStatus] = {}
        self._results: dict[str, ToolResult] = {}

    def approve(self, command_key: str) -> None:
        self._status[command_key] = CommandStatus.APPROVED

    async def execute(self, *, command_key: str, payload: dict[str, Any]) -> ToolResult:
        status = self._status.get(command_key)
        if status == CommandStatus.SUCCEEDED:
            return self._results[command_key]
        if status != CommandStatus.APPROVED:
            raise CommandNotApproved(command_key)
        self._status[command_key] = CommandStatus.EXECUTING
        result = await self._adapter.execute(payload=payload, idempotency_key=command_key)
        if result.status == ToolResultStatus.SUCCEEDED:
            self._status[command_key] = CommandStatus.SUCCEEDED
            self._results[command_key] = result
            return result
        if result.status == ToolResultStatus.UNKNOWN:
            reconciled = await self._adapter.reconcile(idempotency_key=command_key)
            if reconciled is not None:
                self._status[command_key] = CommandStatus.SUCCEEDED
                self._results[command_key] = reconciled
                return reconciled
            self._status[command_key] = CommandStatus.UNKNOWN
            return result
        self._status[command_key] = CommandStatus.FAILED
        return result
