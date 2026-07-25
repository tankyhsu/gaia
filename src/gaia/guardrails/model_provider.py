"""ModelProvider decorator applying input and output guardrail pipelines."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pydantic import BaseModel

from gaia.contracts.models import ModelEndpointProfile, ModelHealth
from gaia.guardrails.pipeline import GuardrailPipeline, GuardrailViolation
from gaia.sdk.guardrail import GuardrailContext, GuardrailStage
from gaia.sdk.model import (
    ModelCallContext,
    ModelMessage,
    ModelProvider,
    ModelResult,
    ModelStreamChunk,
)


class GuardedModelProvider:
    """Keep provider integration separate from application-owned safety policy."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        input_guardrails: GuardrailPipeline | None = None,
        output_guardrails: GuardrailPipeline | None = None,
    ) -> None:
        self._provider = provider
        self._input = input_guardrails or GuardrailPipeline()
        self._output = output_guardrails or GuardrailPipeline()

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        return await self._provider.health(profile)

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult:
        safe_messages = await self._safe_messages(messages, context)
        result = await self._provider.generate_structured(
            profile=profile,
            messages=safe_messages,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            context=context,
        )
        serialized = json.dumps(result.output, ensure_ascii=True, sort_keys=True)
        safe_output = await self._output.evaluate(
            serialized,
            _context(GuardrailStage.OUTPUT, context),
        )
        validated = output_schema.model_validate_json(safe_output)
        return result.model_copy(update={"output": validated.model_dump(mode="json")})

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        safe_messages = await self._safe_messages(messages, context)
        received = ""
        emitted = ""
        async for chunk in self._provider.generate_stream(
            profile=profile,
            messages=safe_messages,
            timeout_seconds=timeout_seconds,
            context=context,
        ):
            received += chunk.delta
            safe = await self._output.evaluate(
                received,
                _context(GuardrailStage.OUTPUT, context),
            )
            if not safe.startswith(emitted):
                raise GuardrailViolation(
                    "GUARDRAIL_STREAM_REWRITE_UNSAFE",
                    "stream-output",
                    "a streamed prefix cannot be changed after emission",
                )
            delta = safe[len(emitted) :]
            emitted = safe
            yield chunk.model_copy(update={"delta": delta})

    async def _safe_messages(
        self,
        messages: list[ModelMessage],
        context: ModelCallContext | None,
    ) -> list[ModelMessage]:
        guardrail_context = _context(GuardrailStage.INPUT, context)
        return [
            message.model_copy(
                update={"content": await self._input.evaluate(message.content, guardrail_context)}
            )
            for message in messages
        ]


def _context(stage: GuardrailStage, context: ModelCallContext | None) -> GuardrailContext:
    return GuardrailContext(
        stage=stage,
        run_id=context.run_id if context is not None else "unbound",
        scenario_id=context.scenario_id if context is not None else "unbound",
    )
