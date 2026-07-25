from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from gaia.observability import (
    ModelInvocation,
    ModelInvocationStatus,
    ModelUsage,
)


def test_model_invocation_records_safe_correlated_evidence() -> None:
    started = datetime.now(UTC)
    invocation = ModelInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        scenario_id="classify",
        provider="openai-compatible",
        model_id="model-1",
        model_parameters_hash="parameters-sha256",
        prompt_version="classify:1.0.0",
        prompt_content_hash="prompt-sha256",
        request_ref="sha256:request",
        response_ref="sha256:response",
        status=ModelInvocationStatus.SUCCEEDED,
        usage=ModelUsage(input_tokens=10, output_tokens=3, total_tokens=13),
        started_at=started,
        completed_at=started + timedelta(milliseconds=120),
        first_token_latency_ms=40,
        duration_ms=120,
    )

    assert invocation.usage is not None
    assert invocation.usage.total_tokens == 13
    assert "content" not in invocation.model_dump()


def test_model_usage_and_status_reject_inconsistent_evidence() -> None:
    with pytest.raises(ValidationError, match="total_tokens"):
        ModelUsage(input_tokens=10, output_tokens=3, total_tokens=12)

    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="requires error_code"):
        ModelInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            scenario_id="classify",
            provider="mock",
            model_id="mock",
            model_parameters_hash="parameters-sha256",
            prompt_version="classify:1.0.0",
            request_ref="sha256:request",
            status=ModelInvocationStatus.FAILED,
            started_at=now,
            completed_at=now,
            duration_ms=0,
        )
