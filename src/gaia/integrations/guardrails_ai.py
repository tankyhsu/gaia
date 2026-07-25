"""Optional Guardrails AI adapter limited to local validation."""

from __future__ import annotations

import inspect
from typing import Any

from gaia.sdk.guardrail import (
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)


class GuardrailsAIValidator:
    """Call ``Guard.validate`` only; model calls remain owned by Gaia."""

    def __init__(
        self,
        guard: Any,
        *,
        guardrail_id: str = "guardrails-ai",
        version: str = "1.0.0",
    ) -> None:
        if not callable(getattr(guard, "validate", None)):
            raise TypeError("guard must provide a validate(content) method")
        self._guard = guard
        self._guardrail_id = guardrail_id
        self._version = version

    @property
    def guardrail_id(self) -> str:
        return self._guardrail_id

    @property
    def guardrail_version(self) -> str:
        return self._version

    async def evaluate(self, content: str, context: GuardrailContext) -> GuardrailResult:
        del context
        outcome = self._guard.validate(content)
        if inspect.isawaitable(outcome):
            outcome = await outcome

        passed = bool(getattr(outcome, "validation_passed", False))
        validated_output = getattr(outcome, "validated_output", None)
        if not passed:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                code="GUARDRAILS_AI_VALIDATION_FAILED",
                reason="configured semantic validation failed",
                risk_score=1.0,
            )
        if isinstance(validated_output, str) and validated_output != content:
            return GuardrailResult(
                action=GuardrailAction.REWRITE,
                content=validated_output,
                code="GUARDRAILS_AI_REWRITTEN",
                risk_score=0.5,
            )
        return GuardrailResult(action=GuardrailAction.ALLOW, risk_score=0.0)
