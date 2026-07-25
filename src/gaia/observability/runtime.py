"""Database-backed operational summary without business-specific semantics."""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from gaia.contracts.models import GateStatus, RunStatus
from gaia.observability.models import (
    DatabaseContention,
    DurationSummary,
    OutboxSummary,
    RuntimeIssue,
    RuntimeSummary,
)
from gaia.persistence.models import HumanGateRecord, OutboxEventRecord, RunRecord

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


class RuntimeObservabilityService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def summary(
        self,
        *,
        window_hours: int = 24,
        stale_after_seconds: int = 300,
    ) -> RuntimeSummary:
        now = datetime.now(UTC)
        since = now - timedelta(hours=window_hours)
        async with self._factory() as session:
            runs = list(
                await session.scalars(
                    select(RunRecord)
                    .where(RunRecord.created_at >= since)
                    .order_by(RunRecord.updated_at.desc())
                )
            )
            gates = list(
                await session.scalars(
                    select(HumanGateRecord).where(HumanGateRecord.created_at >= since)
                )
            )
            outbox = list(await session.scalars(select(OutboxEventRecord)))
            database = await self._database_contention(session)

        status_counts = Counter(item.status for item in runs)
        error_counts = Counter(
            str(item.error_json.get("code"))
            for item in runs
            if item.error_json and item.error_json.get("code")
        )
        completed_durations = [
            _duration_ms(item.created_at, item.updated_at)
            for item in runs
            if item.status not in _ACTIVE_STATUSES and item.status != RunStatus.WAITING_HUMAN.value
        ]
        gate_waits = [
            _duration_ms(item.created_at, item.decided_at or now)
            for item in gates
            if item.decided_at is not None or item.status == GateStatus.PENDING.value
        ]
        stale_before = now - timedelta(seconds=stale_after_seconds)
        stale = [
            item
            for item in runs
            if item.status in _ACTIVE_STATUSES and _aware(item.updated_at) < stale_before
        ]
        pending_gates = [item for item in gates if item.status == GateStatus.PENDING.value]
        issues = _issues(
            runs,
            now=now,
            stale_before=stale_before,
            limit=20,
        )
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
                status_counts[RunStatus.BLOCKED.value] + status_counts[RunStatus.DEGRADED.value],
                total,
            ),
            active_runs=sum(status_counts[item] for item in _ACTIVE_STATUSES),
            stale_runs=len(stale),
            pending_human_gates=len(pending_gates),
            oldest_pending_gate_age_seconds=(
                max(_duration_seconds(item.created_at, now) for item in pending_gates)
                if pending_gates
                else None
            ),
            run_duration=_durations(completed_durations),
            human_gate_wait=_durations(gate_waits),
            error_counts=dict(sorted(error_counts.items())),
            database=database,
            outbox=_outbox_summary(outbox),
            issues=issues,
        )

    async def _database_contention(self, session: AsyncSession) -> DatabaseContention:
        bind = self._factory.kw.get("bind")
        async_engine = bind if isinstance(bind, AsyncEngine) else None
        pool = async_engine.sync_engine.pool if async_engine is not None else None
        backend = session.get_bind().dialect.name
        waiting: int | None = None
        lock_waiting: int | None = None
        if backend == "postgresql":
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          count(*) FILTER (WHERE wait_event_type IS NOT NULL),
                          count(*) FILTER (WHERE wait_event_type = 'Lock')
                        FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_backend_pid()
                          AND state = 'active'
                        """
                    )
                )
            ).one()
            waiting = int(row[0])
            lock_waiting = int(row[1])
        return DatabaseContention(
            backend=backend,
            pool_class=pool.__class__.__name__ if pool is not None else "unknown",
            pool_size=_pool_value(pool, "size"),
            checked_out=_pool_value(pool, "checkedout"),
            overflow=_nonnegative_pool_value(pool, "overflow"),
            waiting_connections=waiting,
            lock_waiting_connections=lock_waiting,
        )


def _issues(
    runs: list[RunRecord],
    *,
    now: datetime,
    stale_before: datetime,
    limit: int,
) -> tuple[RuntimeIssue, ...]:
    values: list[RuntimeIssue] = []
    for item in runs:
        updated_at = _aware(item.updated_at)
        if item.status == RunStatus.WAITING_HUMAN.value:
            bottleneck = "human_gate"
        elif item.status in _ACTIVE_STATUSES and updated_at < stale_before:
            bottleneck = "stale_execution"
        elif item.status in _ISSUE_STATUSES:
            bottleneck = "run_error"
        else:
            continue
        error_code = (
            str(item.error_json.get("code"))
            if item.error_json and item.error_json.get("code")
            else None
        )
        values.append(
            RuntimeIssue(
                run_id=item.run_id,
                scenario_id=item.scenario_id,
                status=item.status,
                bottleneck=bottleneck,
                age_seconds=_duration_seconds(item.created_at, now),
                error_code=error_code,
                updated_at=updated_at,
            )
        )
    return tuple(values[:limit])


def _outbox_summary(records: list[OutboxEventRecord]) -> OutboxSummary:
    counts = Counter(item.status for item in records)
    retrying = sum(
        1
        for item in records
        if item.attempts > 0 and item.status not in {"published", "dead_letter"}
    )
    return OutboxSummary(
        status_counts=dict(sorted(counts.items())),
        pending=counts["pending"],
        retrying=retrying,
        dead_letter=counts["dead_letter"],
    )


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


def _pool_value(pool: Any, name: str) -> int | None:
    method = getattr(pool, name, None)
    if not callable(method):
        return None
    try:
        return int(method())
    except (TypeError, ValueError):
        return None


def _nonnegative_pool_value(pool: Any, name: str) -> int | None:
    value = _pool_value(pool, name)
    return max(0, value) if value is not None else None
