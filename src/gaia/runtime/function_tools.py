"""Runtime registration helpers for declarative function tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gaia.contracts.models import ToolKind
from gaia.runtime.dependencies import WriteToolRegistration
from gaia.sdk.tool import FunctionWriteAdapter, ToolHandler, WriteAdapter, get_tool_spec


def function_write_tool(handler: ToolHandler) -> WriteToolRegistration:
    """Create an explicit Runtime registration from a decorated write function."""

    spec = get_tool_spec(handler)
    if spec.definition.kind != ToolKind.WRITE:
        raise ValueError("function_write_tool requires @write_tool metadata")

    def factory(payload: Mapping[str, Any]) -> WriteAdapter:
        return FunctionWriteAdapter(handler, payload)

    return WriteToolRegistration(spec.definition, factory)
