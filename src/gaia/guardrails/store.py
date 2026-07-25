"""SQLAlchemy guardrail decision sink and run projection."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.guardrails.models import (
    GuardrailDecision,
    GuardrailDecisionSummary,
    GuardrailEvaluationStatus,
    RunGuardrailObservability,
)
from gaia.persistence.models import GuardrailDecisionRecord
from gaia.sdk.guardrail import GuardrailAction, GuardrailStage


class SqlAlchemyGuardrailDecisionStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def record(self, decision: GuardrailDecision) -> None:
        async with self._factory.begin() as session:
            session.add(
                GuardrailDecisionRecord(
                    decision_id=decision.decision_id,
                    run_id=None if decision.run_id == "unbound" else decision.run_id,
                    scenario_id=decision.scenario_id,
                    stage=decision.stage.value,
                    guardrail_id=decision.guardrail_id,
                    guardrail_version=decision.guardrail_version,
                    status=decision.status.value,
                    action=decision.action.value,
                    risk_score=decision.risk_score,
                    input_ref=decision.input_ref,
                    output_ref=decision.output_ref,
                    code=decision.code,
                    started_at=decision.started_at,
                    completed_at=decision.completed_at,
                    duration_ms=decision.duration_ms,
                )
            )

    async def for_run(self, run_id: str) -> RunGuardrailObservability:
        async with self._factory() as session:
            records = list(
                await session.scalars(
                    select(GuardrailDecisionRecord)
                    .where(GuardrailDecisionRecord.run_id == run_id)
                    .order_by(GuardrailDecisionRecord.started_at)
                )
            )
        decisions = tuple(_decision(record) for record in records)
        counts = Counter(item.action.value for item in decisions)
        stages = Counter(item.stage.value for item in decisions)
        durations = [item.duration_ms for item in decisions]
        return RunGuardrailObservability(
            run_id=run_id,
            summary=GuardrailDecisionSummary(
                total=len(decisions),
                allowed=counts[GuardrailAction.ALLOW.value],
                rewritten=counts[GuardrailAction.REWRITE.value],
                blocked=counts[GuardrailAction.BLOCK.value],
                errors=sum(item.status == GuardrailEvaluationStatus.ERROR for item in decisions),
                average_duration_ms=(round(sum(durations) / len(durations)) if durations else None),
                by_stage=dict(sorted(stages.items())),
            ),
            decisions=decisions,
        )


def _decision(record: GuardrailDecisionRecord) -> GuardrailDecision:
    return GuardrailDecision(
        decision_id=record.decision_id,
        run_id=record.run_id or "unbound",
        scenario_id=record.scenario_id,
        stage=GuardrailStage(record.stage),
        guardrail_id=record.guardrail_id,
        guardrail_version=record.guardrail_version,
        status=GuardrailEvaluationStatus(record.status),
        action=GuardrailAction(record.action),
        risk_score=record.risk_score,
        input_ref=record.input_ref,
        output_ref=record.output_ref,
        code=record.code,
        started_at=record.started_at,
        completed_at=record.completed_at,
        duration_ms=record.duration_ms,
    )
