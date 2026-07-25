"""Configurable regex guardrail without business-specific policy."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gaia.sdk.guardrail import (
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)


@dataclass(frozen=True)
class PatternRule:
    pattern: str
    code: str
    action: GuardrailAction = GuardrailAction.BLOCK
    replacement: str = "[REDACTED]"
    flags: int = re.IGNORECASE

    def __post_init__(self) -> None:
        re.compile(self.pattern, self.flags)
        if self.action == GuardrailAction.ALLOW:
            raise ValueError("pattern rules must block or rewrite")


class PatternGuardrail:
    def __init__(
        self,
        guardrail_id: str,
        rules: tuple[PatternRule, ...],
        *,
        version: str = "1.0.0",
    ) -> None:
        if not guardrail_id:
            raise ValueError("guardrail_id must not be empty")
        if not rules:
            raise ValueError("at least one pattern rule is required")
        if not version:
            raise ValueError("guardrail version must not be empty")
        self._guardrail_id = guardrail_id
        self._version = version
        self._rules = tuple((rule, re.compile(rule.pattern, rule.flags)) for rule in rules)

    @property
    def guardrail_id(self) -> str:
        return self._guardrail_id

    @property
    def guardrail_version(self) -> str:
        return self._version

    async def evaluate(self, content: str, context: GuardrailContext) -> GuardrailResult:
        del context
        rewritten = content
        changed = False
        matched_code: str | None = None
        for rule, pattern in self._rules:
            if pattern.search(rewritten) is None:
                continue
            if rule.action == GuardrailAction.BLOCK:
                return GuardrailResult(
                    action=GuardrailAction.BLOCK,
                    code=rule.code,
                    reason="configured content policy matched",
                    risk_score=1.0,
                )
            rewritten = pattern.sub(rule.replacement, rewritten)
            changed = True
            matched_code = matched_code or rule.code
        if changed:
            return GuardrailResult(
                action=GuardrailAction.REWRITE,
                content=rewritten,
                code=matched_code,
                risk_score=0.5,
            )
        return GuardrailResult(action=GuardrailAction.ALLOW, risk_score=0.0)
