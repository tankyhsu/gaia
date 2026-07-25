"""Mock write adapter with observable idempotency and timeout injection."""

from __future__ import annotations

from typing import Any

from gaia.contracts.models import (
    RiskLevel,
    RunMode,
    ToolDefinition,
    ToolKind,
    ToolResult,
    ToolResultStatus,
)


class MockResourceWriteAdapter:
    definition = ToolDefinition(
        name="set_resource_status",
        version="1.0.0",
        kind=ToolKind.WRITE,
        risk_level=RiskLevel.HIGH,
        required_roles=["operator"],
        timeout_seconds=5,
        max_retries=1,
        idempotent=True,
        allowed_environments=[RunMode.MOCK, RunMode.SANDBOX],
    )

    def __init__(self, resources: dict[str, dict[str, Any]], mode: str = "normal") -> None:
        self._resources = resources
        self._mode = mode
        self.success_count = 0
        self._results: dict[str, ToolResult] = {}

    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult:
        if idempotency_key in self._results:
            return self._results[idempotency_key]
        if self._mode == "timeout_unknown":
            return ToolResult(
                ok=False, status=ToolResultStatus.UNKNOWN, data={}, error_code="TOOL_TIMEOUT"
            )
        resource = self._resources[str(payload["resource_id"])]
        resource["status"] = str(payload["target_status"])
        resource["version"] = int(resource["version"]) + 1
        self.success_count += 1
        result = ToolResult(ok=True, status=ToolResultStatus.SUCCEEDED, data=resource.copy())
        self._results[idempotency_key] = result
        return result

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None:
        return self._results.get(idempotency_key)
