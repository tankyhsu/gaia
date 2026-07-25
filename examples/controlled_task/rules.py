"""Versioned pure rule evaluation for controlled-task."""

from __future__ import annotations

from examples.controlled_task.models import ControlledTaskIntent


def evaluate_intent(intent: ControlledTaskIntent) -> str | None:
    if intent.operation is None or intent.resource_id is None:
        return "RULE-CT-001"
    if intent.operation == "set_status" and (intent.target_status is None or intent.reason is None):
        return "RULE-CT-003"
    return None
