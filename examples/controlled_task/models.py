"""Scenario-owned declarations, independent of runtime and adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ControlledTaskIntent(BaseModel):
    operation: Literal["inspect", "set_status"] | None = None
    resource_id: str | None = None
    target_status: Literal["active", "paused"] | None = None
    reason: str | None = None
