"""The only permitted Gaia Run lifecycle transitions."""

from __future__ import annotations

from gaia.contracts.models import RunStatus


class InvalidStateTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.RECEIVED: frozenset(
        {RunStatus.VALIDATED, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.VALIDATED: frozenset(
        {RunStatus.RUNNING, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_HUMAN,
            RunStatus.DEGRADED,
            RunStatus.BLOCKED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_HUMAN: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED, RunStatus.CANCELLED}),
    RunStatus.DEGRADED: frozenset(),
    RunStatus.BLOCKED: frozenset(),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def validate_transition(current: RunStatus, next_status: RunStatus) -> None:
    if next_status not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition {current} -> {next_status}")
