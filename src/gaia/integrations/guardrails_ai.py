"""Optional adapter for application-configured Guardrails AI validators."""

from __future__ import annotations

import asyncio
import inspect
import json
import warnings
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from gaia.spi.guardrail import (
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)

type GuardrailsMetadataFactory = Callable[
    [str, GuardrailContext],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]


class GuardrailsAIValidator:
    """Run an explicitly configured ``Guard`` inside a Gaia guardrail stage."""

    def __init__(
        self,
        guard: Any,
        *,
        guardrail_id: str = "guardrails-ai",
        version: str = "1.0.0",
        correctable: bool = False,
        metadata: Mapping[str, Any] | None = None,
        metadata_factory: GuardrailsMetadataFactory | None = None,
    ) -> None:
        if not callable(getattr(guard, "validate", None)):
            raise TypeError("guard must provide a validate(content) method")
        self._guard = guard
        self._guardrail_id = guardrail_id
        self._version = version
        self._correctable = correctable
        self._metadata = dict(metadata or {})
        self._metadata_factory = metadata_factory

    @property
    def guardrail_id(self) -> str:
        return self._guardrail_id

    @property
    def guardrail_version(self) -> str:
        return self._version

    async def evaluate(self, content: str, context: GuardrailContext) -> GuardrailResult:
        metadata = dict(self._metadata)
        metadata.update(context.metadata)
        if self._metadata_factory is not None:
            dynamic_metadata = self._metadata_factory(content, context)
            if inspect.isawaitable(dynamic_metadata):
                dynamic_metadata = await dynamic_metadata
            if not isinstance(dynamic_metadata, Mapping):
                raise TypeError("metadata_factory must return a mapping")
            metadata.update(dynamic_metadata)

        kwargs = {"metadata": metadata} if metadata else {}
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Could not obtain an event loop.*",
                module="guardrails.validator_service",
            )
            validate = self._guard.validate
            if inspect.iscoroutinefunction(validate):
                outcome = await validate(content, **kwargs)
            else:
                outcome = await asyncio.to_thread(validate, content, **kwargs)
            if inspect.isawaitable(outcome):
                outcome = await outcome

        passed = bool(getattr(outcome, "validation_passed", False))
        validated_output = getattr(outcome, "validated_output", None)
        if getattr(outcome, "reask", None) is not None:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                code="GUARDRAILS_AI_REASK_REQUIRED",
                reason="configured validation requested another model call",
                risk_score=1.0,
                correctable=self._correctable,
            )
        if not passed:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                code="GUARDRAILS_AI_VALIDATION_FAILED",
                reason="configured semantic validation failed",
                risk_score=1.0,
                correctable=self._correctable,
            )
        rewritten = _serialize_validated_output(validated_output)
        if rewritten is not None and rewritten != content:
            return GuardrailResult(
                action=GuardrailAction.REWRITE,
                content=rewritten,
                code="GUARDRAILS_AI_REWRITTEN",
                risk_score=0.5,
            )
        return GuardrailResult(action=GuardrailAction.ALLOW, risk_score=0.0)


def _serialize_validated_output(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
