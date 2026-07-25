"""Public contracts for application-owned guardrails."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GuardrailStage(StrEnum):
    INPUT = "input"
    RETRIEVAL = "retrieval"
    OUTPUT = "output"
    TOOL_INPUT = "tool_input"
    TOOL_OUTPUT = "tool_output"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    REWRITE = "rewrite"
    BLOCK = "block"


class GuardrailFailureMode(StrEnum):
    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"


class GuardrailContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: GuardrailStage
    run_id: str = "unbound"
    scenario_id: str = "unbound"
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuardrailResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: GuardrailAction
    content: str | None = None
    code: str | None = None
    reason: str | None = None
    risk_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def action_has_required_evidence(self) -> GuardrailResult:
        if self.action == GuardrailAction.REWRITE and self.content is None:
            raise ValueError("rewrite guardrail result requires content")
        if self.action == GuardrailAction.BLOCK and not self.code:
            raise ValueError("block guardrail result requires a code")
        return self


class ContentGuardrail(Protocol):
    @property
    def guardrail_id(self) -> str: ...

    @property
    def guardrail_version(self) -> str: ...

    async def evaluate(self, content: str, context: GuardrailContext) -> GuardrailResult: ...
