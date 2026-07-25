"""Deterministic budget accounting for a single Run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gaia.contracts.models import ExecutionPolicy


class BudgetExceeded(ValueError):
    pass


class RunBudget:
    def __init__(self, policy: ExecutionPolicy, received_at: datetime) -> None:
        self._policy = policy
        self._received_at = received_at.astimezone(UTC)
        self._steps = 0
        self._model_calls = 0
        self._waiting_since: datetime | None = None
        self._waited = timedelta()

    def enter_step(self) -> None:
        self._steps += 1
        if self._steps > self._policy.max_steps:
            raise BudgetExceeded("max_steps exceeded")

    def record_model_call(self) -> None:
        self._model_calls += 1
        if self._model_calls > self._policy.max_model_calls:
            raise BudgetExceeded("max_model_calls exceeded")

    def enter_human_wait(self, at: datetime) -> None:
        self._waiting_since = at.astimezone(UTC)

    def leave_human_wait(self, at: datetime) -> None:
        if self._waiting_since is not None:
            self._waited += at.astimezone(UTC) - self._waiting_since
            self._waiting_since = None

    def assert_duration(self, now: datetime) -> None:
        elapsed = now.astimezone(UTC) - self._received_at - self._waited
        if self._waiting_since is not None:
            elapsed -= now.astimezone(UTC) - self._waiting_since
        if elapsed.total_seconds() > self._policy.max_duration_seconds:
            raise BudgetExceeded("max_duration_seconds exceeded")
