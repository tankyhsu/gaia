"""Ordered guardrail evaluation with stable, payload-free failures."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from gaia.guardrails.models import GuardrailDecision, GuardrailEvaluationStatus
from gaia.guardrails.sinks import (
    GuardrailDecisionSink,
    NullGuardrailDecisionSink,
)
from gaia.sdk.guardrail import (
    ContentGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailFailureMode,
)


class GuardrailViolation(ValueError):
    def __init__(self, code: str, guardrail_id: str, reason: str | None = None) -> None:
        super().__init__(f"{code}:{guardrail_id}")
        self.code = code
        self.guardrail_id = guardrail_id
        self.reason = reason


class GuardrailPipeline:
    def __init__(
        self,
        guardrails: Iterable[ContentGuardrail] = (),
        *,
        sink: GuardrailDecisionSink | None = None,
        failure_mode: GuardrailFailureMode = GuardrailFailureMode.FAIL_CLOSED,
        audit_required: bool = False,
    ) -> None:
        self._guardrails = tuple(guardrails)
        self._sink = sink or NullGuardrailDecisionSink()
        self._failure_mode = failure_mode
        self._audit_required = audit_required
        ids = [item.guardrail_id for item in self._guardrails]
        if len(ids) != len(set(ids)):
            raise ValueError("guardrail_id must be unique within a pipeline")

    @property
    def guardrail_ids(self) -> tuple[str, ...]:
        return tuple(item.guardrail_id for item in self._guardrails)

    async def evaluate(self, content: str, context: GuardrailContext) -> str:
        current = content
        for guardrail in self._guardrails:
            started_at = datetime.now(UTC)
            started = perf_counter()
            input_ref = _digest(current)
            try:
                result = await guardrail.evaluate(current, context)
            except Exception:
                action = (
                    GuardrailAction.BLOCK
                    if self._failure_mode == GuardrailFailureMode.FAIL_CLOSED
                    else GuardrailAction.ALLOW
                )
                decision = GuardrailDecision(
                    decision_id=str(uuid4()),
                    run_id=context.run_id,
                    scenario_id=context.scenario_id,
                    stage=context.stage,
                    guardrail_id=guardrail.guardrail_id,
                    guardrail_version=guardrail.guardrail_version,
                    status=GuardrailEvaluationStatus.ERROR,
                    action=action,
                    input_ref=input_ref,
                    code="GUARDRAIL_EXECUTION_FAILED",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    duration_ms=_elapsed_ms(started),
                )
                await self._record(decision)
                if action == GuardrailAction.BLOCK:
                    raise GuardrailViolation(
                        decision.code or "GUARDRAIL_EXECUTION_FAILED",
                        guardrail.guardrail_id,
                    ) from None
                continue
            output = result.content or "" if result.action == GuardrailAction.REWRITE else current
            decision = GuardrailDecision(
                decision_id=str(uuid4()),
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                stage=context.stage,
                guardrail_id=guardrail.guardrail_id,
                guardrail_version=guardrail.guardrail_version,
                status=GuardrailEvaluationStatus.EVALUATED,
                action=result.action,
                risk_score=result.risk_score,
                input_ref=input_ref,
                output_ref=(_digest(output) if result.action == GuardrailAction.REWRITE else None),
                code=result.code,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=_elapsed_ms(started),
            )
            await self._record(decision)
            if result.action == GuardrailAction.BLOCK:
                raise GuardrailViolation(
                    result.code or "GUARDRAIL_BLOCKED",
                    guardrail.guardrail_id,
                    result.reason,
                )
            if result.action == GuardrailAction.REWRITE:
                current = output or ""
        return current

    async def _record(self, decision: GuardrailDecision) -> None:
        try:
            await self._sink.record(decision)
        except Exception:
            if self._audit_required:
                raise GuardrailViolation(
                    "GUARDRAIL_AUDIT_UNAVAILABLE",
                    decision.guardrail_id,
                ) from None


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
