from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from gaia.contracts.models import (
    ModelCapabilities,
    ModelEndpointProfile,
    ModelHealth,
)
from gaia.observability import InstrumentedModelProvider
from gaia.observability.models import ModelInvocation, ModelInvocationStatus
from gaia.sdk.model import (
    ModelCallContext,
    ModelMessage,
    ModelResult,
    ModelStreamChunk,
    ModelUsage,
)


class Output(BaseModel):
    answer: str


class RecordingSink:
    def __init__(self) -> None:
        self.items: list[ModelInvocation] = []

    async def record(self, invocation: ModelInvocation) -> None:
        self.items.append(invocation)


class StubProvider:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        return ModelHealth(
            provider_id=profile.provider_id,
            model_id=profile.model_id,
            healthy=True,
            capabilities=profile.capabilities,
            checked_at=datetime.now(UTC),
        )

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult:
        del messages, output_schema, timeout_seconds, context
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("secret provider response")
        return ModelResult(
            output={"answer": "private model response"},
            model_id=profile.model_id,
            usage=ModelUsage(input_tokens=7, output_tokens=3, total_tokens=10),
        )


class BrokenSink:
    async def record(self, invocation: ModelInvocation) -> None:
        del invocation
        raise RuntimeError("observability backend unavailable")


class StreamingStubProvider(StubProvider):
    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ):
        del messages, timeout_seconds, context
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("temporary stream failure")
        yield ModelStreamChunk(delta="ok", model_id=profile.model_id)


def profile() -> ModelEndpointProfile:
    return ModelEndpointProfile(
        provider_id="mock",
        protocol="mock",
        model_id="test-model",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=False,
            max_context_tokens=None,
        ),
        data_residency="local",
        timeout_seconds=1,
    )


async def test_wrapper_records_safe_success_evidence_and_usage() -> None:
    sink = RecordingSink()
    provider = InstrumentedModelProvider(StubProvider(), sink)
    result = await provider.generate_structured(
        profile=profile(),
        messages=[ModelMessage(role="user", content="private prompt text")],
        output_schema=Output,
        timeout_seconds=1,
        context=ModelCallContext(
            run_id="run-1",
            scenario_id="scenario-1",
            prompt_version="prompt:1.0.0",
            prompt_content_hash="abc",
        ),
    )

    assert result.output == {"answer": "private model response"}
    assert len(sink.items) == 1
    invocation = sink.items[0]
    assert invocation.status == ModelInvocationStatus.SUCCEEDED
    assert invocation.usage is not None
    assert invocation.usage.total_tokens == 10
    serialized = invocation.model_dump_json()
    assert "private prompt text" not in serialized
    assert "private model response" not in serialized


async def test_wrapper_records_retry_and_final_failure() -> None:
    sink = RecordingSink()
    provider = InstrumentedModelProvider(
        StubProvider(failures=2),
        sink,
        max_retries=1,
        retryable=lambda error: isinstance(error, TimeoutError),
    )

    with pytest.raises(TimeoutError):
        await provider.generate_structured(
            profile=profile(),
            messages=[],
            output_schema=Output,
            timeout_seconds=1,
            context=ModelCallContext(
                run_id="run-2",
                scenario_id="scenario-1",
                prompt_version="prompt:1.0.0",
            ),
        )

    assert sink.items[0].status == ModelInvocationStatus.FAILED
    assert sink.items[0].retry_count == 1
    assert sink.items[0].error_code == "MODEL_PROVIDER_ERROR"
    assert "secret provider response" not in sink.items[0].model_dump_json()


async def test_observation_failure_does_not_change_model_result() -> None:
    result = await InstrumentedModelProvider(StubProvider(), BrokenSink()).generate_structured(
        profile=profile(),
        messages=[],
        output_schema=Output,
        timeout_seconds=1,
    )
    assert result.output == {"answer": "private model response"}


async def test_stream_retries_only_before_the_first_chunk() -> None:
    sink = RecordingSink()
    provider = InstrumentedModelProvider(
        StreamingStubProvider(failures=1),
        sink,
        max_retries=1,
        retryable=lambda error: isinstance(error, TimeoutError),
    )

    chunks = [
        chunk
        async for chunk in provider.generate_stream(
            profile=profile().model_copy(
                update={
                    "capabilities": profile().capabilities.model_copy(update={"streaming": True})
                }
            ),
            messages=[],
            timeout_seconds=1,
        )
    ]

    assert [chunk.delta for chunk in chunks] == ["ok"]
    assert sink.items[0].status == ModelInvocationStatus.SUCCEEDED
    assert sink.items[0].retry_count == 1
