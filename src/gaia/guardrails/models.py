"""Payload-free operational evidence for guardrail evaluations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gaia.sdk.guardrail import GuardrailAction, GuardrailStage


class GuardrailEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    ERROR = "error"


class GuardrailDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    run_id: str
    scenario_id: str
    stage: GuardrailStage
    guardrail_id: str
    guardrail_version: str
    status: GuardrailEvaluationStatus
    action: GuardrailAction
    risk_score: float | None = Field(default=None, ge=0, le=1)
    input_ref: str
    output_ref: str | None = None
    code: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> GuardrailDecision:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.action == GuardrailAction.REWRITE and self.output_ref is None:
            raise ValueError("rewrite decision requires output_ref")
        if self.action == GuardrailAction.BLOCK and not self.code:
            raise ValueError("block decision requires code")
        if self.status == GuardrailEvaluationStatus.ERROR and not self.code:
            raise ValueError("error decision requires code")
        return self


class GuardrailDecisionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int
    allowed: int
    rewritten: int
    blocked: int
    errors: int
    average_duration_ms: int | None = None
    by_stage: dict[str, int]


class RunGuardrailObservability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    summary: GuardrailDecisionSummary
    decisions: tuple[GuardrailDecision, ...]
