"""Read-only resource adapter for the golden scenario."""

from __future__ import annotations

from typing import Any

from gaia.contracts.models import RiskLevel, ToolDefinition, ToolKind, ToolResult, ToolResultStatus

DEFAULT_RESOURCES: dict[str, dict[str, Any]] = {
    "res-001": {
        "resource_id": "res-001",
        "organization": "org-alpha",
        "status": "active",
        "version": 3,
        "readable_roles": ["reader", "operator", "approver"],
    },
    "res-002": {
        "resource_id": "res-002",
        "organization": "org-alpha",
        "status": "paused",
        "version": 7,
        "readable_roles": ["operator", "approver"],
    },
    "res-003": {
        "resource_id": "res-003",
        "organization": "org-beta",
        "status": "active",
        "version": 2,
        "readable_roles": ["reader", "operator", "approver"],
    },
}


class MockResourceReadTool:
    definition = ToolDefinition(
        name="read_resource",
        version="1.0.0",
        kind=ToolKind.READ,
        risk_level=RiskLevel.LOW,
        required_roles=[],
        timeout_seconds=5,
        max_retries=1,
        idempotent=True,
    )

    def __init__(self, resources: dict[str, dict[str, Any]] | None = None) -> None:
        self._resources = (
            resources
            if resources is not None
            else {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
        )

    async def execute(self, payload: dict[str, Any]) -> ToolResult:
        resource = self._resources.get(str(payload.get("resource_id")))
        if resource is None:
            return ToolResult(
                ok=False, status=ToolResultStatus.FAILED, data={}, error_code="INVALID_REQUEST"
            )
        return ToolResult(ok=True, status=ToolResultStatus.SUCCEEDED, data=resource)
