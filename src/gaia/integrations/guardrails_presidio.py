"""Optional Presidio adapter for PII detection and anonymization."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from gaia.sdk.guardrail import (
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)


class PresidioGuardrail:
    """Use injected Presidio engines without making them Gaia dependencies."""

    def __init__(
        self,
        analyzer: Any,
        anonymizer: Any | None = None,
        *,
        guardrail_id: str = "presidio-pii",
        version: str = "1.0.0",
        action: GuardrailAction = GuardrailAction.REWRITE,
        entities: tuple[str, ...] | None = None,
        language: str = "en",
        score_threshold: float = 0.5,
    ) -> None:
        if action not in (GuardrailAction.BLOCK, GuardrailAction.REWRITE):
            raise ValueError("PresidioGuardrail action must block or rewrite")
        if action == GuardrailAction.REWRITE and anonymizer is None:
            raise ValueError("rewrite action requires a Presidio anonymizer")
        if not 0 <= score_threshold <= 1:
            raise ValueError("score_threshold must be between 0 and 1")
        self._analyzer = analyzer
        self._anonymizer = anonymizer
        self._guardrail_id = guardrail_id
        self._version = version
        self._action = action
        self._entities = entities
        self._language = language
        self._score_threshold = score_threshold

    @classmethod
    def create_default(cls, **kwargs: Any) -> PresidioGuardrail:
        try:
            analyzer_type = import_module("presidio_analyzer").AnalyzerEngine
            anonymizer_type = import_module("presidio_anonymizer").AnonymizerEngine
        except ImportError as error:
            raise RuntimeError(
                "CONFIG_OPTIONAL_DEPENDENCY_MISSING: install gaia-framework[presidio]"
            ) from error
        return cls(analyzer_type(), anonymizer_type(), **kwargs)

    @property
    def guardrail_id(self) -> str:
        return self._guardrail_id

    @property
    def guardrail_version(self) -> str:
        return self._version

    async def evaluate(self, content: str, context: GuardrailContext) -> GuardrailResult:
        del context
        results = self._analyzer.analyze(
            text=content,
            entities=list(self._entities) if self._entities else None,
            language=self._language,
            score_threshold=self._score_threshold,
        )
        matches = [
            item for item in results if float(getattr(item, "score", 0.0)) >= self._score_threshold
        ]
        if not matches:
            return GuardrailResult(action=GuardrailAction.ALLOW, risk_score=0.0)

        risk_score = max(float(getattr(item, "score", 0.0)) for item in matches)
        if self._action == GuardrailAction.BLOCK:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                code="PII_DETECTED",
                reason="personally identifiable information detected",
                risk_score=risk_score,
            )

        anonymizer = self._anonymizer
        assert anonymizer is not None
        anonymized = anonymizer.anonymize(
            text=content,
            analyzer_results=matches,
        )
        return GuardrailResult(
            action=GuardrailAction.REWRITE,
            content=str(anonymized.text),
            code="PII_REDACTED",
            risk_score=risk_score,
        )
