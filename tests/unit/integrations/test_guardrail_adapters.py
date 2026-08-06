from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

from gaia.integrations import GuardrailsAIValidator, PresidioGuardrail
from gaia.spi.guardrail import GuardrailAction, GuardrailContext, GuardrailStage


class FakeAnalyzer:
    def analyze(self, **kwargs: object) -> list[SimpleNamespace]:
        assert kwargs["language"] == "en"
        return [SimpleNamespace(score=0.92, entity_type="EMAIL_ADDRESS")]


class FakeAnonymizer:
    def anonymize(self, **kwargs: object) -> SimpleNamespace:
        assert kwargs["analyzer_results"]
        return SimpleNamespace(text="contact <EMAIL_ADDRESS>")


class FakeGuard:
    def __init__(self, *, passed: bool, output: str | None = None) -> None:
        self.passed = passed
        self.output = output
        self.calls: list[str] = []

    def validate(self, content: str) -> SimpleNamespace:
        self.calls.append(content)
        return SimpleNamespace(
            validation_passed=self.passed,
            validated_output=self.output,
        )


class MetadataGuard:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def validate(self, content: str, *, metadata: dict[str, Any]) -> SimpleNamespace:
        self.calls.append((content, metadata))
        return SimpleNamespace(validation_passed=True, validated_output=content)


class StructuredOutputGuard:
    def validate(self, content: str) -> SimpleNamespace:
        del content
        return SimpleNamespace(
            validation_passed=True,
            validated_output={"allowed": True, "score": 5},
        )


class AsyncGuard:
    async def validate(self, content: str) -> SimpleNamespace:
        await asyncio.sleep(0)
        return SimpleNamespace(validation_passed=True, validated_output=content)


class ReaskGuard:
    def validate(self, content: str) -> SimpleNamespace:
        return SimpleNamespace(
            validation_passed=True,
            validated_output=f"fixed:{content}",
            reask={"incorrect_value": content},
        )


class ThreadRecordingGuard:
    def __init__(self) -> None:
        self.thread_id: int | None = None

    def validate(self, content: str) -> SimpleNamespace:
        self.thread_id = threading.get_ident()
        return SimpleNamespace(validation_passed=True, validated_output=content)


async def test_presidio_adapter_rewrites_detected_pii() -> None:
    guardrail = PresidioGuardrail(FakeAnalyzer(), FakeAnonymizer())

    result = await guardrail.evaluate(
        "contact person@example.com",
        GuardrailContext(stage=GuardrailStage.INPUT),
    )

    assert result.action == GuardrailAction.REWRITE
    assert result.content == "contact <EMAIL_ADDRESS>"
    assert result.risk_score == 0.92


async def test_guardrails_ai_adapter_only_calls_validate() -> None:
    guard = FakeGuard(passed=True, output='{"score": 5}')
    validator = GuardrailsAIValidator(guard)

    result = await validator.evaluate(
        '{"score": 7}',
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert guard.calls == ['{"score": 7}']
    assert result.action == GuardrailAction.REWRITE
    assert result.content == '{"score": 5}'


async def test_guardrails_ai_adapter_blocks_failed_validation() -> None:
    validator = GuardrailsAIValidator(FakeGuard(passed=False))

    result = await validator.evaluate(
        "invalid",
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert result.action == GuardrailAction.BLOCK
    assert result.code == "GUARDRAILS_AI_VALIDATION_FAILED"


async def test_guardrails_ai_adapter_passes_merged_runtime_metadata() -> None:
    guard = MetadataGuard()
    validator = GuardrailsAIValidator(
        guard,
        metadata={"sources": ["policy-v1"], "tenant": "default"},
        metadata_factory=lambda content, context: {
            "content_length": len(content),
            "tenant": context.scenario_id,
        },
    )

    result = await validator.evaluate(
        "answer",
        GuardrailContext(
            stage=GuardrailStage.RETRIEVAL,
            run_id="run-7",
            scenario_id="hr-onboarding",
            metadata={"query_function": "application-owned", "tenant": "request"},
        ),
    )

    assert result.action == GuardrailAction.ALLOW
    assert guard.calls == [
        (
            "answer",
            {
                "sources": ["policy-v1"],
                "tenant": "hr-onboarding",
                "query_function": "application-owned",
                "content_length": 6,
            },
        )
    ]


async def test_guardrails_ai_adapter_serializes_structured_validated_output() -> None:
    validator = GuardrailsAIValidator(StructuredOutputGuard())

    result = await validator.evaluate(
        '{"score":7}',
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert result.action == GuardrailAction.REWRITE
    assert result.content == '{"allowed":true,"score":5}'


async def test_guardrails_ai_adapter_accepts_async_validate() -> None:
    validator = GuardrailsAIValidator(AsyncGuard())

    result = await validator.evaluate(
        "answer",
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert result.action == GuardrailAction.ALLOW


async def test_guardrails_ai_adapter_returns_reask_to_gaia_as_block() -> None:
    validator = GuardrailsAIValidator(ReaskGuard(), correctable=True)

    result = await validator.evaluate(
        "answer",
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert result.action == GuardrailAction.BLOCK
    assert result.code == "GUARDRAILS_AI_REASK_REQUIRED"
    assert result.correctable is True


async def test_guardrails_ai_adapter_runs_sync_validate_off_event_loop() -> None:
    guard = ThreadRecordingGuard()
    validator = GuardrailsAIValidator(guard)
    event_loop_thread_id = threading.get_ident()

    result = await validator.evaluate(
        "answer",
        GuardrailContext(stage=GuardrailStage.OUTPUT),
    )

    assert result.action == GuardrailAction.ALLOW
    assert guard.thread_id is not None
    assert guard.thread_id != event_loop_thread_id
