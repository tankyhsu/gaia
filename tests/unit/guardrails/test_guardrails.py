from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from gaia.contracts.models import ModelCapabilities, ModelEndpointProfile, ModelHealth
from gaia.guardrails import (
    GuardedModelProvider,
    GuardrailDecision,
    GuardrailPipeline,
    GuardrailViolation,
    PatternGuardrail,
    PatternRule,
)
from gaia.observability import InstrumentedModelProvider
from gaia.observability.models import ModelInvocation
from gaia.sdk.guardrail import (
    GuardrailAction,
    GuardrailContext,
    GuardrailFailureMode,
    GuardrailResult,
    GuardrailStage,
)
from gaia.sdk.model import (
    ModelCallContext,
    ModelMessage,
    ModelResult,
    ModelStreamChunk,
)


class Answer(BaseModel):
    answer: str


class RecordingProvider:
    def __init__(self, output: str = "safe response") -> None:
        self.messages: list[ModelMessage] = []
        self.output = output

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
        del output_schema, timeout_seconds, context
        self.messages = messages
        return ModelResult(output={"answer": self.output}, model_id=profile.model_id)

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        del messages, timeout_seconds, context
        for delta in ("safe ", self.output):
            yield ModelStreamChunk(delta=delta, model_id=profile.model_id)


class RecordingDecisionSink:
    def __init__(self) -> None:
        self.decisions: list[GuardrailDecision] = []

    async def record(self, decision: GuardrailDecision) -> None:
        self.decisions.append(decision)


class RecordingInvocationSink:
    def __init__(self) -> None:
        self.invocations: list[ModelInvocation] = []

    async def record(self, invocation: ModelInvocation) -> None:
        self.invocations.append(invocation)


class BrokenDecisionSink:
    async def record(self, decision: GuardrailDecision) -> None:
        del decision
        raise RuntimeError("audit database unavailable")


class FailingGuardrail:
    guardrail_id = "unavailable-policy"
    guardrail_version = "2.1.0"

    async def evaluate(
        self,
        content: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        del content, context
        raise RuntimeError("scanner unavailable")


def profile() -> ModelEndpointProfile:
    return ModelEndpointProfile(
        provider_id="mock",
        protocol="mock",
        model_id="test",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=True,
            max_context_tokens=None,
        ),
        data_residency="local",
        timeout_seconds=1,
    )


async def test_pipeline_rewrites_configured_input_without_business_policy() -> None:
    guardrail = PatternGuardrail(
        "secrets",
        (
            PatternRule(
                pattern=r"token-[a-z0-9]+",
                code="SECRET_DETECTED",
                action=GuardrailAction.REWRITE,
            ),
        ),
    )
    provider = RecordingProvider()
    guarded = GuardedModelProvider(
        provider,
        input_guardrails=GuardrailPipeline((guardrail,)),
    )

    result = await guarded.generate_structured(
        profile=profile(),
        messages=[ModelMessage(role="user", content="use token-private")],
        output_schema=Answer,
        timeout_seconds=1,
    )

    assert result.output == {"answer": "safe response"}
    assert provider.messages[0].content == "use [REDACTED]"


async def test_pipeline_blocks_output_with_stable_payload_free_error() -> None:
    guardrail = PatternGuardrail(
        "output-policy",
        (PatternRule(pattern="forbidden", code="OUTPUT_BLOCKED"),),
    )
    guarded = GuardedModelProvider(
        RecordingProvider("forbidden"),
        output_guardrails=GuardrailPipeline((guardrail,)),
    )

    with pytest.raises(GuardrailViolation, match="OUTPUT_BLOCKED:output-policy") as captured:
        await guarded.generate_structured(
            profile=profile(),
            messages=[],
            output_schema=Answer,
            timeout_seconds=1,
        )

    assert "forbidden" not in str(captured.value)


async def test_streaming_output_is_checked_before_each_delta_is_emitted() -> None:
    guardrail = PatternGuardrail(
        "stream-policy",
        (PatternRule(pattern="blocked", code="STREAM_BLOCKED"),),
    )
    guarded = GuardedModelProvider(
        RecordingProvider("blocked"),
        output_guardrails=GuardrailPipeline((guardrail,)),
    )
    stream = guarded.generate_stream(
        profile=profile(),
        messages=[],
        timeout_seconds=1,
    )

    first = await anext(stream)
    assert first.delta == "safe "
    with pytest.raises(GuardrailViolation, match="STREAM_BLOCKED"):
        await anext(stream)


async def test_pattern_guardrail_reports_allow_when_no_rule_matches() -> None:
    guardrail = PatternGuardrail(
        "policy",
        (PatternRule(pattern="blocked", code="BLOCKED"),),
    )
    result = await guardrail.evaluate(
        "safe",
        GuardrailContext(stage=GuardrailStage.INPUT),
    )
    assert result.action == GuardrailAction.ALLOW


async def test_pipeline_records_payload_free_versioned_decision() -> None:
    sink = RecordingDecisionSink()
    guardrail = PatternGuardrail(
        "secrets",
        (
            PatternRule(
                pattern="customer-secret",
                code="SECRET_DETECTED",
                action=GuardrailAction.REWRITE,
            ),
        ),
        version="3.0.0",
    )
    pipeline = GuardrailPipeline((guardrail,), sink=sink)

    result = await pipeline.evaluate(
        "customer-secret",
        GuardrailContext(
            stage=GuardrailStage.TOOL_INPUT,
            run_id="run-1",
            scenario_id="scenario-1",
        ),
    )

    assert result == "[REDACTED]"
    assert len(sink.decisions) == 1
    decision = sink.decisions[0]
    assert decision.guardrail_version == "3.0.0"
    assert decision.stage == GuardrailStage.TOOL_INPUT
    assert decision.action == GuardrailAction.REWRITE
    assert decision.code == "SECRET_DETECTED"
    assert decision.input_ref.startswith("sha256:")
    assert decision.output_ref is not None
    assert "customer-secret" not in decision.model_dump_json()


async def test_guardrail_failure_modes_are_explicit_and_audited() -> None:
    closed_sink = RecordingDecisionSink()
    closed = GuardrailPipeline((FailingGuardrail(),), sink=closed_sink)
    with pytest.raises(GuardrailViolation, match="GUARDRAIL_EXECUTION_FAILED"):
        await closed.evaluate(
            "payload",
            GuardrailContext(stage=GuardrailStage.RETRIEVAL),
        )
    assert closed_sink.decisions[0].action == GuardrailAction.BLOCK
    assert closed_sink.decisions[0].status.value == "error"

    open_sink = RecordingDecisionSink()
    opened = GuardrailPipeline(
        (FailingGuardrail(),),
        sink=open_sink,
        failure_mode=GuardrailFailureMode.FAIL_OPEN,
    )
    assert (
        await opened.evaluate(
            "payload",
            GuardrailContext(stage=GuardrailStage.TOOL_OUTPUT),
        )
        == "payload"
    )
    assert open_sink.decisions[0].action == GuardrailAction.ALLOW


async def test_required_audit_blocks_when_decision_sink_is_unavailable() -> None:
    pipeline = GuardrailPipeline(
        (
            PatternGuardrail(
                "policy",
                (PatternRule(pattern="blocked", code="BLOCKED"),),
            ),
        ),
        sink=BrokenDecisionSink(),
        audit_required=True,
    )

    with pytest.raises(GuardrailViolation, match="GUARDRAIL_AUDIT_UNAVAILABLE"):
        await pipeline.evaluate(
            "safe",
            GuardrailContext(stage=GuardrailStage.INPUT),
        )


def test_guardrail_contract_covers_the_five_runtime_stages() -> None:
    assert {stage.value for stage in GuardrailStage} == {
        "input",
        "retrieval",
        "output",
        "tool_input",
        "tool_output",
    }


async def test_outer_instrumentation_records_guardrail_block() -> None:
    invocation_sink = RecordingInvocationSink()
    guarded = GuardedModelProvider(
        RecordingProvider("forbidden"),
        output_guardrails=GuardrailPipeline(
            (
                PatternGuardrail(
                    "output-policy",
                    (PatternRule(pattern="forbidden", code="OUTPUT_BLOCKED"),),
                ),
            )
        ),
    )
    provider = InstrumentedModelProvider(guarded, invocation_sink)

    with pytest.raises(GuardrailViolation):
        await provider.generate_structured(
            profile=profile(),
            messages=[],
            output_schema=Answer,
            timeout_seconds=1,
        )

    assert len(invocation_sink.invocations) == 1
    assert invocation_sink.invocations[0].status.value == "failed"
    assert invocation_sink.invocations[0].error_code == "OUTPUT_BLOCKED"
