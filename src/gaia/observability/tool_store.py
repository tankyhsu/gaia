"""SQLAlchemy tool-invocation sink and read projection."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.observability.models import (
    DurationSummary,
    RunToolObservability,
    ToolInvocation,
    ToolInvocationStatus,
    ToolInvocationSummary,
)
from gaia.persistence.models import ToolInvocationRecord


class SqlAlchemyToolInvocationStore:
    """Persist and inspect payload-free tool evidence."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def record(self, invocation: ToolInvocation) -> None:
        async with self._factory.begin() as session:
            session.add(
                ToolInvocationRecord(
                    invocation_id=invocation.invocation_id,
                    run_id=invocation.run_id,
                    scenario_id=invocation.scenario_id,
                    tool_name=invocation.tool_name,
                    tool_version=invocation.tool_version,
                    status=invocation.status.value,
                    input_ref=invocation.input_ref,
                    output_ref=invocation.output_ref,
                    started_at=invocation.started_at,
                    completed_at=invocation.completed_at,
                    duration_ms=invocation.duration_ms,
                    error_code=invocation.error_code,
                )
            )

    async def for_run(self, run_id: str) -> RunToolObservability:
        async with self._factory() as session:
            records = tuple(
                await session.scalars(
                    select(ToolInvocationRecord)
                    .where(ToolInvocationRecord.run_id == run_id)
                    .order_by(ToolInvocationRecord.started_at)
                )
            )
        invocations = tuple(
            ToolInvocation(
                invocation_id=item.invocation_id,
                run_id=item.run_id,
                scenario_id=item.scenario_id,
                tool_name=item.tool_name,
                tool_version=item.tool_version,
                status=ToolInvocationStatus(item.status),
                input_ref=item.input_ref,
                output_ref=item.output_ref,
                started_at=item.started_at,
                completed_at=item.completed_at,
                duration_ms=item.duration_ms,
                error_code=item.error_code,
            )
            for item in records
        )
        durations = sorted(item.duration_ms for item in invocations)
        return RunToolObservability(
            run_id=run_id,
            summary=ToolInvocationSummary(
                total=len(invocations),
                succeeded=sum(
                    item.status == ToolInvocationStatus.SUCCEEDED for item in invocations
                ),
                failed=sum(item.status == ToolInvocationStatus.FAILED for item in invocations),
                blocked=sum(item.status == ToolInvocationStatus.BLOCKED for item in invocations),
                timed_out=sum(
                    item.status == ToolInvocationStatus.TIMED_OUT for item in invocations
                ),
                duration=DurationSummary(
                    average_ms=(round(sum(durations) / len(durations)) if durations else None),
                    p50_ms=_percentile(durations, 0.50),
                    p95_ms=_percentile(durations, 0.95),
                ),
            ),
            invocations=invocations,
        )


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return values[index]
