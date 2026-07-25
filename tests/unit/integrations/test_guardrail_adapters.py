from __future__ import annotations

from types import SimpleNamespace

from gaia.integrations import GuardrailsAIValidator, PresidioGuardrail
from gaia.sdk.guardrail import GuardrailAction, GuardrailContext, GuardrailStage


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
