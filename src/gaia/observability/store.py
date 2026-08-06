"""SQLAlchemy model-invocation sink and read projection."""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.observability.models import (
    DurationSummary,
    ModelInvocation,
    ModelInvocationStatus,
    ModelInvocationSummary,
    RunModelObservability,
)
from gaia.persistence.models import ModelInvocationRecord
from gaia.spi.model import ModelUsage


class SqlAlchemyModelInvocationStore:
    """Persist and inspect safe model evidence in Gaia's operational store."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def record(self, invocation: ModelInvocation) -> None:
        async with self._factory.begin() as session:
            session.add(
                ModelInvocationRecord(
                    invocation_id=invocation.invocation_id,
                    run_id=None if invocation.run_id == "unbound" else invocation.run_id,
                    scenario_id=invocation.scenario_id,
                    provider=invocation.provider,
                    model_id=invocation.model_id,
                    model_parameters_hash=invocation.model_parameters_hash,
                    prompt_version=invocation.prompt_version,
                    prompt_content_hash=invocation.prompt_content_hash,
                    request_ref=invocation.request_ref,
                    response_ref=invocation.response_ref,
                    status=invocation.status.value,
                    usage_json=(
                        None
                        if invocation.usage is None
                        else invocation.usage.model_dump(mode="json")
                    ),
                    started_at=invocation.started_at,
                    completed_at=invocation.completed_at,
                    first_token_latency_ms=invocation.first_token_latency_ms,
                    duration_ms=invocation.duration_ms,
                    retry_count=invocation.retry_count,
                    error_code=invocation.error_code,
                )
            )

    async def for_run(self, run_id: str) -> RunModelObservability:
        async with self._factory() as session:
            records = list(
                await session.scalars(
                    select(ModelInvocationRecord)
                    .where(ModelInvocationRecord.run_id == run_id)
                    .order_by(ModelInvocationRecord.started_at)
                )
            )
        invocations = tuple(_model(item) for item in records)
        return RunModelObservability(
            run_id=run_id,
            summary=_summary(invocations),
            invocations=invocations,
        )


def _model(record: ModelInvocationRecord) -> ModelInvocation:
    return ModelInvocation(
        invocation_id=record.invocation_id,
        run_id=record.run_id or "unbound",
        scenario_id=record.scenario_id,
        provider=record.provider,
        model_id=record.model_id,
        model_parameters_hash=record.model_parameters_hash,
        prompt_version=record.prompt_version,
        prompt_content_hash=record.prompt_content_hash,
        request_ref=record.request_ref,
        response_ref=record.response_ref,
        status=ModelInvocationStatus(record.status),
        usage=None if record.usage_json is None else ModelUsage.model_validate(record.usage_json),
        started_at=record.started_at,
        completed_at=record.completed_at,
        first_token_latency_ms=record.first_token_latency_ms,
        duration_ms=record.duration_ms,
        retry_count=record.retry_count,
        error_code=record.error_code,
    )


def _summary(invocations: tuple[ModelInvocation, ...]) -> ModelInvocationSummary:
    costs: defaultdict[str, float] = defaultdict(float)
    input_tokens = output_tokens = total_tokens = 0
    for item in invocations:
        if item.usage is None:
            continue
        input_tokens += item.usage.input_tokens
        output_tokens += item.usage.output_tokens
        total_tokens += item.usage.total_tokens
        if item.usage.currency is not None and item.usage.estimated_cost is not None:
            costs[item.usage.currency] += item.usage.estimated_cost
    durations = sorted(item.duration_ms for item in invocations)
    return ModelInvocationSummary(
        total=len(invocations),
        succeeded=sum(item.status == ModelInvocationStatus.SUCCEEDED for item in invocations),
        failed=sum(item.status == ModelInvocationStatus.FAILED for item in invocations),
        retry_count=sum(item.retry_count for item in invocations),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_by_currency=dict(sorted(costs.items())),
        duration=DurationSummary(
            average_ms=(round(sum(durations) / len(durations)) if durations else None),
            p50_ms=_percentile(durations, 0.50),
            p95_ms=_percentile(durations, 0.95),
        ),
    )


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return values[index]
