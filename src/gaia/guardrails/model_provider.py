"""ModelProvider decorator applying input and output guardrail pipelines."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pydantic import BaseModel, ValidationError

from gaia.contracts.models import ModelEndpointProfile, ModelHealth
from gaia.guardrails.pipeline import GuardrailPipeline, GuardrailViolation
from gaia.spi.guardrail import GuardrailContext, GuardrailStage
from gaia.spi.model import (
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
        output_correction_attempts: int = 0,
    ) -> None:
        self._provider = provider
        self._input = input_guardrails or GuardrailPipeline()
        self._output = output_guardrails or GuardrailPipeline()
        if output_correction_attempts < 0:
            raise ValueError("output_correction_attempts must be non-negative")
        self._output_correction_attempts = output_correction_attempts

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
        correction_messages = safe_messages
        for attempt in range(self._output_correction_attempts + 1):
            result = await self._provider.generate_structured(
                profile=profile,
                messages=correction_messages,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                context=context,
            )
            serialized = json.dumps(result.output, ensure_ascii=True, sort_keys=True)
            try:
                safe_output = await self._output.evaluate(
                    serialized,
                    _context(GuardrailStage.OUTPUT, context),
                )
                validated = output_schema.model_validate_json(safe_output)
            except GuardrailViolation as error:
                if not error.correctable:
                    raise
                if attempt >= self._output_correction_attempts:
                    raise _output_invalid(error.guardrail_id) from error
                correction_messages = _with_correction(
                    safe_messages,
                    f"validator={error.guardrail_id}; code={error.code}",
                    output_schema,
                )
                continue
            except ValidationError as error:
                if attempt >= self._output_correction_attempts:
                    raise _output_invalid("structured-output") from error
                correction_messages = _with_correction(
                    safe_messages,
                    _schema_feedback(error),
                    output_schema,
                )
                continue
            return result.model_copy(update={"output": validated.model_dump(mode="json")})
        raise AssertionError("unreachable output correction state")

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        safe_messages = await self._safe_messages(messages, context)
        source = self._provider.generate_stream(
            profile=profile,
            messages=safe_messages,
            timeout_seconds=timeout_seconds,
            context=context,
        )
        if self._output.is_empty:
            async for chunk in source:
                yield chunk
            return

        # Strict output policy cannot retract a prefix that was already delivered. Buffer the
        # provider stream, evaluate once, and only then release policy-approved content.
        chunks = [chunk async for chunk in source]
        if not chunks:
            return
        received = "".join(chunk.delta for chunk in chunks)
        safe = await self._output.evaluate(
            received,
            _context(GuardrailStage.OUTPUT, context),
        )
        if safe == received:
            for chunk in chunks:
                yield chunk
            return
        for chunk in chunks[:-1]:
            if chunk.usage is not None or chunk.finish_reason is not None:
                yield chunk.model_copy(update={"delta": ""})
        yield chunks[-1].model_copy(update={"delta": safe})

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


def _with_correction(
    messages: list[ModelMessage],
    feedback: str,
    output_schema: type[BaseModel],
) -> list[ModelMessage]:
    fields = ", ".join(output_schema.model_fields)
    return [
        *messages,
        ModelMessage(
            role="system",
            content=(
                "The previous response was rejected as a correctable structured-output "
                f"error ({feedback}). Generate a new response matching schema "
                f"{output_schema.__name__} with fields: {fields}. Do not discuss the error."
            ),
        ),
    ]


def _schema_feedback(error: ValidationError) -> str:
    issues = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "root"
        issues.append(f"{location}:{item['type']}")
    return "schema=" + ",".join(issues)


def _output_invalid(guardrail_id: str) -> GuardrailViolation:
    return GuardrailViolation(
        "MODEL_OUTPUT_INVALID",
        guardrail_id,
        "bounded structured-output correction was exhausted",
        correctable=True,
    )
