"""Guardrail decision sinks with isolated fan-out."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

from gaia.guardrails.models import GuardrailDecision

logger = logging.getLogger(__name__)


class GuardrailDecisionSink(Protocol):
    async def record(self, decision: GuardrailDecision) -> None: ...


class NullGuardrailDecisionSink:
    async def record(self, decision: GuardrailDecision) -> None:
        del decision


class CompositeGuardrailDecisionSink:
    def __init__(self, sinks: Sequence[GuardrailDecisionSink]) -> None:
        self._sinks = tuple(sinks)

    async def record(self, decision: GuardrailDecision) -> None:
        results = await asyncio.gather(
            *(sink.record(decision) for sink in self._sinks),
            return_exceptions=True,
        )
        failures = [item for item in results if isinstance(item, BaseException)]
        if failures:
            logger.warning(
                "gaia_guardrail_sink_failed decision_id=%s failures=%s",
                decision.decision_id,
                len(failures),
            )
            raise RuntimeError("GUARDRAIL_AUDIT_SINK_FAILED")
