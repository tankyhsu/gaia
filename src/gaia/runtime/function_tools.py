"""Runtime registration helpers for declarative function tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gaia._authoring.tool import (
    FunctionReadTool,
    FunctionWriteAdapter,
    get_tool_spec,
)
from gaia.contracts.models import ToolKind
from gaia.runtime.dependencies import ReadToolRegistration, WriteToolRegistration
from gaia.spi.tool import ToolHandler, WriteAdapter


def function_tool(handler: ToolHandler) -> ReadToolRegistration | WriteToolRegistration:
    """Create the matching Runtime registration for a decorated function."""

    spec = get_tool_spec(handler)
    if spec.definition.kind == ToolKind.READ:
        return ReadToolRegistration(spec.definition, FunctionReadTool(handler))
    return function_write_tool(handler)


def function_write_tool(handler: ToolHandler) -> WriteToolRegistration:
    """Create an explicit Runtime registration from a decorated write function."""

    spec = get_tool_spec(handler)
    if spec.definition.kind != ToolKind.WRITE:
        raise ValueError("function_write_tool requires @write_tool metadata")

    def factory(payload: Mapping[str, Any]) -> WriteAdapter:
        return FunctionWriteAdapter(handler, payload)

    return WriteToolRegistration(spec.definition, factory)
