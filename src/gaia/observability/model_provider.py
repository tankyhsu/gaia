"""Provider-neutral model instrumentation without payload capture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel

from gaia.contracts.models import ModelEndpointProfile, ModelHealth
from gaia.observability.models import ModelInvocation, ModelInvocationStatus
from gaia.spi.model import (
    ModelCallContext,
    ModelMessage,
    ModelProvider,
    ModelResult,
    ModelStreamChunk,
)

logger = logging.getLogger(__name__)


class ModelInvocationSink(Protocol):
    """Best-effort destination for safe model-call evidence."""

    async def record(self, invocation: ModelInvocation) -> None: ...


class NullModelInvocationSink:
    async def record(self, invocation: ModelInvocation) -> None:
        del invocation


class CompositeModelInvocationSink:
    """Fan out independently so one broken exporter does not block the others."""

    def __init__(self, sinks: Sequence[ModelInvocationSink]) -> None:
        self._sinks = tuple(sinks)

    async def record(self, invocation: ModelInvocation) -> None:
        results = await asyncio.gather(
            *(sink.record(invocation) for sink in self._sinks),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.warning(
                    "gaia_model_observation_sink_failed error_type=%s",
                    type(result).__name__,
                )


class InstrumentedModelProvider:
    """Record one logical invocation while preserving the wrapped provider contract."""

    def __init__(
        self,
        provider: ModelProvider,
        sink: ModelInvocationSink | None = None,
        *,
        max_retries: int = 0,
        retryable: Callable[[Exception], bool] | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self._provider = provider
        self._sink = sink or NullModelInvocationSink()
        self._max_retries = max_retries
        self._retryable = retryable or (lambda _error: False)

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
        call_context = context or ModelCallContext(
            run_id="unbound",
            scenario_id="unbound",
            prompt_version="unbound",
        )
        invocation_id = str(uuid4())
        started_at = datetime.now(UTC)
        started = perf_counter()
        request_ref = _digest(
            {
                "messages": [message.model_dump(mode="json") for message in messages],
                "output_schema": output_schema.model_json_schema(),
            }
        )
        parameters_hash = _digest(
            {
                "provider_id": profile.provider_id,
                "protocol": profile.protocol,
                "model_id": profile.model_id,
                "artifact_version": profile.artifact_version,
                "timeout_seconds": timeout_seconds,
            }
        )
        retry_count = 0
        try:
            while True:
                try:
                    result = await self._provider.generate_structured(
                        profile=profile,
                        messages=messages,
                        output_schema=output_schema,
                        timeout_seconds=timeout_seconds,
                        context=context,
                    )
                    break
                except Exception as error:
                    if retry_count >= self._max_retries or not self._retryable(error):
                        raise
                    retry_count += 1
            invocation = ModelInvocation(
                invocation_id=invocation_id,
                run_id=call_context.run_id,
                scenario_id=call_context.scenario_id,
                provider=profile.provider_id,
                model_id=result.model_id,
                model_parameters_hash=parameters_hash,
                prompt_version=call_context.prompt_version,
                prompt_content_hash=call_context.prompt_content_hash,
                request_ref=request_ref,
                response_ref=_digest(result.output),
                status=ModelInvocationStatus.SUCCEEDED,
                usage=result.usage,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                first_token_latency_ms=result.first_token_latency_ms,
                duration_ms=_elapsed_ms(started),
                retry_count=retry_count,
            )
            await _record_safely(self._sink, invocation)
            return result
        except Exception as error:
            invocation = ModelInvocation(
                invocation_id=invocation_id,
                run_id=call_context.run_id,
                scenario_id=call_context.scenario_id,
                provider=profile.provider_id,
                model_id=profile.model_id,
                model_parameters_hash=parameters_hash,
                prompt_version=call_context.prompt_version,
                prompt_content_hash=call_context.prompt_content_hash,
                request_ref=request_ref,
                status=ModelInvocationStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=_elapsed_ms(started),
                retry_count=retry_count,
                error_code=_error_code(error),
            )
            await _record_safely(self._sink, invocation)
            raise

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        call_context = context or ModelCallContext(
            run_id="unbound",
            scenario_id="unbound",
            prompt_version="unbound",
        )
        invocation_id = str(uuid4())
        started_at = datetime.now(UTC)
        started = perf_counter()
        request_ref = _digest(
            {"messages": [message.model_dump(mode="json") for message in messages]}
        )
        parameters_hash = _digest(
            {
                "provider_id": profile.provider_id,
                "protocol": profile.protocol,
                "model_id": profile.model_id,
                "artifact_version": profile.artifact_version,
                "timeout_seconds": timeout_seconds,
                "streaming": True,
            }
        )
        output_parts: list[str] = []
        usage = None
        model_id = profile.model_id
        first_token_latency_ms = None
        retry_count = 0
        emitted_any = False
        try:
            while True:
                try:
                    async for chunk in self._provider.generate_stream(
                        profile=profile,
                        messages=messages,
                        timeout_seconds=timeout_seconds,
                        context=context,
                    ):
                        model_id = chunk.model_id
                        if chunk.delta:
                            if first_token_latency_ms is None:
                                first_token_latency_ms = _elapsed_ms(started)
                            output_parts.append(chunk.delta)
                        if chunk.usage is not None:
                            usage = chunk.usage
                        emitted_any = True
                        yield chunk
                    break
                except Exception as error:
                    if (
                        emitted_any
                        or retry_count >= self._max_retries
                        or not self._retryable(error)
                    ):
                        raise
                    retry_count += 1
            await _record_safely(
                self._sink,
                ModelInvocation(
                    invocation_id=invocation_id,
                    run_id=call_context.run_id,
                    scenario_id=call_context.scenario_id,
                    provider=profile.provider_id,
                    model_id=model_id,
                    model_parameters_hash=parameters_hash,
                    prompt_version=call_context.prompt_version,
                    prompt_content_hash=call_context.prompt_content_hash,
                    request_ref=request_ref,
                    response_ref=_digest("".join(output_parts)),
                    status=ModelInvocationStatus.SUCCEEDED,
                    usage=usage,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    first_token_latency_ms=first_token_latency_ms,
                    duration_ms=_elapsed_ms(started),
                    retry_count=retry_count,
                ),
            )
        except Exception as error:
            await _record_safely(
                self._sink,
                ModelInvocation(
                    invocation_id=invocation_id,
                    run_id=call_context.run_id,
                    scenario_id=call_context.scenario_id,
                    provider=profile.provider_id,
                    model_id=model_id,
                    model_parameters_hash=parameters_hash,
                    prompt_version=call_context.prompt_version,
                    prompt_content_hash=call_context.prompt_content_hash,
                    request_ref=request_ref,
                    status=ModelInvocationStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    first_token_latency_ms=first_token_latency_ms,
                    duration_ms=_elapsed_ms(started),
                    retry_count=retry_count,
                    error_code=_error_code(error),
                ),
            )
            raise


async def _record_safely(sink: ModelInvocationSink, invocation: ModelInvocation) -> None:
    try:
        await sink.record(invocation)
    except Exception as error:
        logger.warning(
            "gaia_model_observation_failed invocation_id=%s error_type=%s",
            invocation.invocation_id,
            type(error).__name__,
        )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _error_code(error: Exception) -> str:
    value = getattr(error, "code", None)
    if value is not None:
        return str(getattr(value, "value", value))
    return "MODEL_PROVIDER_ERROR"
