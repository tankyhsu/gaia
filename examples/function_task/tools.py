"""Reference read/write tools for the `function_task` example.

Business logic only: a read tool over an in-memory resource table, and a write tool
that mutates it. Everything else -- discovery, adapters, policy enforcement, the
HumanGate lifecycle -- is handled by the framework via `gaia.yaml`.
"""

from __future__ import annotations

from typing import Any

from gaia import read_tool, write_tool
from gaia.contracts.models import RiskLevel, RunMode

# A reference app has no external system to write to, so a plain in-memory dict stands
# in for "the business record". `_executions` backs the write tool's reconcile handler so
# a crash-then-retry with the same idempotency key returns the original result instead of
# re-running the mutation.
_RESOURCES: dict[str, str] = {"widget-1": "draft"}
_EXECUTIONS: dict[str, dict[str, Any]] = {}


@read_tool("function_task.lookup_resource", allowed_environments=(RunMode.MOCK,))
async def lookup_resource(resource_id: str) -> dict[str, Any]:
    return {"resource_id": resource_id, "status": _RESOURCES.get(resource_id, "unknown")}


async def _reconcile_publish(*, idempotency_key: str) -> dict[str, Any] | None:
    return _EXECUTIONS.get(idempotency_key)


@write_tool(
    "function_task.publish_resource",
    risk_level=RiskLevel.HIGH,
    reconcile=_reconcile_publish,
    allowed_environments=(RunMode.MOCK,),
)
async def publish_resource(resource_id: str, *, idempotency_key: str) -> dict[str, Any]:
    _RESOURCES[resource_id] = "published"
    result = {"resource_id": resource_id, "status": "published"}
    _EXECUTIONS[idempotency_key] = result
    return result
