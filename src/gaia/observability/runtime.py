"""Read-only operational summary projected from the active Runtime."""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime, timedelta

from gaia.contracts.models import ErrorCategory, RunSnapshot, RunStatus
from gaia.diagnostics.error_catalog import error_descriptor
from gaia.observability.models import (
    DatabaseContention,
    DurationSummary,
    OutboxSummary,
    RuntimeIssue,
    RuntimeSummary,
)
from gaia.runtime.contracts import RuntimeEngine

_ACTIVE_STATUSES = {
    RunStatus.RECEIVED.value,
    RunStatus.VALIDATED.value,
    RunStatus.RUNNING.value,
}
_ISSUE_STATUSES = {
    RunStatus.DEGRADED.value,
    RunStatus.BLOCKED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


def stopped_by_control(run: RunSnapshot) -> bool:
    """True when a Run ended because a control refused it, rather than broke.

    An approver saying no, or a policy denying a tool, is the outcome Gaia
    exists to produce. Counting it as a failure -- or queueing it for an
    operator -- reports a working control as a fault.

    The distinction comes from the error catalog's `ErrorCategory`, not from a
    list of codes kept here. A second list would drift from the catalog the
    moment a code is added, and the drift would show up as this view quietly
    misclassifying it.
    """

    if run.status != RunStatus.BLOCKED or run.error is None:
        return False
    return error_descriptor(run.error.code).category in {
        ErrorCategory.POLICY,
        ErrorCategory.AUTHORIZATION,
    }


class RuntimeObservabilityService:
    """Project Runtime state without owning or querying an execution database."""

    def __init__(self, runtime: RuntimeEngine | None) -> None:
        self._runtime = runtime

    async def summary(
        self,
        *,
        window_hours: int = 24,
        stale_after_seconds: int = 300,
    ) -> RuntimeSummary:
        now = datetime.now(UTC)
        since = now - timedelta(hours=window_hours)
        runs: list[RunSnapshot] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while self._runtime is not None:
            page = await self._runtime.list_runs(
                organization=None,
                limit=100,
                cursor=cursor,
            )
            runs.extend(item for item in page.items if item.created_at >= since)
            if (
                page.next_cursor is None
                or not page.items
                or min(item.created_at for item in page.items) < since
                or page.next_cursor in seen_cursors
            ):
                break
            cursor = page.next_cursor
            seen_cursors.add(cursor)

        status_counts = Counter(item.status.value for item in runs)
        error_counts = Counter(
            str(item.error.code) for item in runs if item.error is not None
        )
        completed_durations = [
            _duration_ms(item.created_at, item.updated_at)
            for item in runs
            if item.status.value not in _ACTIVE_STATUSES
            and item.status != RunStatus.WAITING_HUMAN
        ]
        stale_before = now - timedelta(seconds=stale_after_seconds)
        stale = [
            item
            for item in runs
            if item.status.value in _ACTIVE_STATUSES
            and item.updated_at < stale_before
        ]
        pending = [item for item in runs if item.status == RunStatus.WAITING_HUMAN]
        total = len(runs)
        return RuntimeSummary(
            window_hours=window_hours,
            stale_after_seconds=stale_after_seconds,
            generated_at=now,
            total_runs=total,
            status_counts=dict(sorted(status_counts.items())),
            success_rate=_rate(status_counts[RunStatus.SUCCEEDED.value], total),
            failure_rate=_rate(status_counts[RunStatus.FAILED.value], total),
            blocked_rate=_rate(
                status_counts[RunStatus.BLOCKED.value]
                + status_counts[RunStatus.DEGRADED.value],
                total,
            ),
            stopped_by_control=sum(1 for item in runs if stopped_by_control(item)),
            active_runs=sum(status_counts[item] for item in _ACTIVE_STATUSES),
            stale_runs=len(stale),
            pending_human_gates=len(pending),
            oldest_pending_gate_age_seconds=(
                max(_duration_seconds(item.updated_at, now) for item in pending)
                if pending
                else None
            ),
            run_duration=_durations(completed_durations),
            human_gate_wait=DurationSummary(),
            error_counts=dict(sorted(error_counts.items())),
            database=DatabaseContention(
                backend="temporal" if self._runtime is not None else "unconfigured",
                pool_class=(
                    "TemporalVisibility"
                    if self._runtime is not None
                    else "RuntimeProjection"
                ),
            ),
            outbox=OutboxSummary(),
            needs_attention=sum(
                1
                for item in runs
                if item.error is not None
                and str(item.error.code) == "SIDE_EFFECT_UNKNOWN"
            ),
            issues=_issues(
                runs,
                now=now,
                stale_before=stale_before,
                limit=20,
            ),
        )


def _issues(
    runs: list[RunSnapshot],
    *,
    now: datetime,
    stale_before: datetime,
    limit: int,
) -> tuple[RuntimeIssue, ...]:
    values: list[RuntimeIssue] = []
    for item in runs:
        if item.status == RunStatus.WAITING_HUMAN:
            bottleneck = "human_gate"
        elif item.status.value in _ACTIVE_STATUSES and item.updated_at < stale_before:
            bottleneck = "stale_execution"
        elif stopped_by_control(item):
            # A Run a control deliberately refused is not work waiting for an
            # operator -- it is the system doing its job. Listing an approver's
            # rejection under "needs attention", as a "run error", tells the
            # reader the opposite of what happened.
            continue
        elif item.status.value in _ISSUE_STATUSES:
            bottleneck = "run_error"
        else:
            continue
        values.append(
            RuntimeIssue(
                run_id=item.run_id,
                scenario_id=item.scenario_id,
                status=item.status.value,
                bottleneck=bottleneck,
                age_seconds=_duration_seconds(item.created_at, now),
                error_code=None if item.error is None else str(item.error.code),
                trace_id=item.trace_id,
                updated_at=item.updated_at,
            )
        )
    return tuple(values[:limit])


def _durations(values: list[int]) -> DurationSummary:
    if not values:
        return DurationSummary()
    ordered = sorted(values)
    return DurationSummary(
        average_ms=round(sum(ordered) / len(ordered)),
        p50_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
    )


def _percentile(ordered: list[int], quantile: float) -> int:
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _duration_ms(start: datetime, end: datetime) -> int:
    return max(0, round((_aware(end) - _aware(start)).total_seconds() * 1000))


def _duration_seconds(start: datetime, end: datetime) -> int:
    return max(0, round((_aware(end) - _aware(start)).total_seconds()))


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
