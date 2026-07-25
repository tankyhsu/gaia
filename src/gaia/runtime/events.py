"""Event helpers. Persistence commits the event with its status transition."""

from __future__ import annotations

from datetime import UTC, datetime

from gaia.contracts.models import ActorType, EventStatus, RunEvent


def new_event(
    *, event_id: str, run_id: str, sequence: int, actor: ActorType, step: str, status: EventStatus
) -> RunEvent:
    return RunEvent(
        event_id=event_id,
        run_id=run_id,
        sequence=sequence,
        timestamp=datetime.now(UTC),
        actor=actor,
        step=step,
        status=status,
        source_refs=[],
        rule_refs=[],
    )
