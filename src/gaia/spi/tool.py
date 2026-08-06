"""Implementation-free tool ports shared by applications and the Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from gaia.contracts.models import ApprovalView, RiskLevel, ToolDefinition, ToolResult

ToolValue = Mapping[str, Any] | BaseModel | ToolResult
ToolHandler = Callable[..., Awaitable[ToolValue]]
ReconcileHandler = Callable[..., Awaitable[ToolValue | None]]
ToolReference = str | ToolHandler


@dataclass(frozen=True)
class ScenarioSideEffect:
    """A requested write that the Gaia Runtime must authorize and execute."""

    step_id: str
    tool_name: str
    payload: Mapping[str, Any]
    reason: str
    risk_level: RiskLevel
    depends_on: tuple[str, ...] = ()
    approval_view: ApprovalView | None = None
    rule_refs: tuple[str, ...] = ()
    uncertainty_rule_refs: tuple[str, ...] = ()


class ReadTool(Protocol):
    definition: ToolDefinition

    async def execute(self, payload: dict[str, Any]) -> ToolResult: ...


class WriteAdapter(Protocol):
    definition: ToolDefinition

    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult: ...

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None: ...


class ScenarioTools(Protocol):
    """Run-scoped tools exposed to one scenario."""

    async def call(self, tool: ToolReference, /, **payload: Any) -> ToolResult: ...

    def propose(
        self,
        tool: ToolReference,
        /,
        *,
        step_id: str,
        payload: Mapping[str, Any],
        reason: str,
        depends_on: tuple[str, ...] = (),
        approval_view: ApprovalView | None = None,
        rule_refs: tuple[str, ...] = (),
        uncertainty_rule_refs: tuple[str, ...] = (),
    ) -> ScenarioSideEffect:
        """Create a policy-scoped write proposal without executing its adapter."""
        ...
