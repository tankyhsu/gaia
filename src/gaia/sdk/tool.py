"""Read/write tool ports; scenario code only declares tool use."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel

from gaia.contracts.models import (
    RiskLevel,
    RunMode,
    ToolDefinition,
    ToolKind,
    ToolResult,
    ToolResultStatus,
)

_TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SPEC_ATTRIBUTE = "__gaia_tool_spec__"

ToolValue = Mapping[str, Any] | BaseModel | ToolResult
ToolHandler = Callable[..., Awaitable[ToolValue]]
ReconcileHandler = Callable[..., Awaitable[ToolValue | None]]


class ReadTool(Protocol):
    definition: ToolDefinition

    async def execute(self, payload: dict[str, Any]) -> ToolResult: ...


class WriteAdapter(Protocol):
    definition: ToolDefinition

    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult: ...

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None: ...


@dataclass(frozen=True)
class FunctionToolSpec:
    """Immutable function metadata used by read and write adapters."""

    definition: ToolDefinition
    handler: ToolHandler
    reconcile: ReconcileHandler | None = None

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.definition.name) is None:
            raise ValueError("tool name must match ^[a-z0-9][a-z0-9._-]{0,127}$")
        if not inspect.iscoroutinefunction(self.handler):
            raise TypeError("tool handler must be async")
        if self.definition.kind == ToolKind.WRITE:
            if self.reconcile is None:
                raise ValueError("write tool requires an explicit reconcile handler")
            if not inspect.iscoroutinefunction(self.reconcile):
                raise TypeError("write tool reconcile handler must be async")
        elif self.reconcile is not None:
            raise ValueError("read tool cannot declare a reconcile handler")


HandlerType = TypeVar("HandlerType", bound=ToolHandler)


def read_tool(
    name: str,
    *,
    version: str = "1.0.0",
    required_roles: tuple[str, ...] = (),
    timeout_seconds: int = 10,
    allowed_environments: tuple[RunMode, ...] = (RunMode.MOCK,),
) -> Callable[[HandlerType], HandlerType]:
    """Attach a read-only ToolDefinition to an async Python function."""

    return _tool_decorator(
        ToolDefinition(
            name=name,
            version=version,
            kind=ToolKind.READ,
            risk_level=RiskLevel.LOW,
            required_roles=list(required_roles),
            timeout_seconds=timeout_seconds,
            max_retries=0,
            idempotent=True,
            allowed_environments=list(allowed_environments),
        )
    )


def write_tool(
    name: str,
    *,
    risk_level: RiskLevel,
    required_roles: tuple[str, ...],
    reconcile: ReconcileHandler,
    version: str = "1.0.0",
    timeout_seconds: int = 10,
    max_retries: int = 0,
    allowed_environments: tuple[RunMode, ...] = (RunMode.MOCK,),
) -> Callable[[HandlerType], HandlerType]:
    """Declare an idempotent write function with mandatory reconciliation."""

    return _tool_decorator(
        ToolDefinition(
            name=name,
            version=version,
            kind=ToolKind.WRITE,
            risk_level=risk_level,
            required_roles=list(required_roles),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            idempotent=True,
            allowed_environments=list(allowed_environments),
        ),
        reconcile=reconcile,
    )


def _tool_decorator(
    definition: ToolDefinition,
    *,
    reconcile: ReconcileHandler | None = None,
) -> Callable[[HandlerType], HandlerType]:
    def decorate(handler: HandlerType) -> HandlerType:
        spec = FunctionToolSpec(
            definition=definition,
            handler=handler,
            reconcile=reconcile,
        )
        setattr(handler, _SPEC_ATTRIBUTE, spec)
        return handler

    return decorate


def get_tool_spec(handler: ToolHandler) -> FunctionToolSpec:
    try:
        return cast(FunctionToolSpec, getattr(handler, _SPEC_ATTRIBUTE))
    except AttributeError as error:
        raise ValueError("tool handler is missing @read_tool or @write_tool metadata") from error


class FunctionReadTool:
    """ReadTool adapter for a decorated async function."""

    def __init__(self, handler: ToolHandler) -> None:
        self._spec = get_tool_spec(handler)
        if self._spec.definition.kind != ToolKind.READ:
            raise ValueError("FunctionReadTool requires @read_tool metadata")
        self.definition = self._spec.definition

    async def execute(self, payload: dict[str, Any]) -> ToolResult:
        return _tool_result(await self._spec.handler(**payload))


class FunctionWriteAdapter:
    """WriteAdapter created for one authorized side-effect payload."""

    def __init__(self, handler: ToolHandler, payload: Mapping[str, Any]) -> None:
        self._spec = get_tool_spec(handler)
        if self._spec.definition.kind != ToolKind.WRITE:
            raise ValueError("FunctionWriteAdapter requires @write_tool metadata")
        self.definition = self._spec.definition
        self._payload = dict(payload)

    async def execute(self, *, payload: dict[str, Any], idempotency_key: str) -> ToolResult:
        if payload != self._payload:
            raise ValueError("write tool payload changed after authorization")
        return _tool_result(await self._spec.handler(**payload, idempotency_key=idempotency_key))

    async def reconcile(self, *, idempotency_key: str) -> ToolResult | None:
        handler = self._spec.reconcile
        if handler is None:  # pragma: no cover - protected by FunctionToolSpec validation
            raise RuntimeError("write tool reconcile handler is missing")
        value = await handler(idempotency_key=idempotency_key)
        return None if value is None else _tool_result(value)


def _tool_result(value: ToolValue) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    if not isinstance(data, Mapping):
        raise TypeError("tool handler must return a mapping, BaseModel, or ToolResult")
    return ToolResult(
        ok=True,
        status=ToolResultStatus.SUCCEEDED,
        data=dict(data),
    )
