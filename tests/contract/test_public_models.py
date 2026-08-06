from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gaia.contracts.models import (
    ErrorResponse,
    HumanGateDecisionRequest,
    RunRequest,
    canonical_json,
    request_hash,
)
from gaia.diagnostics.error_catalog import operational_error


def test_run_request_is_strict_and_hash_is_stable() -> None:
    request = RunRequest.model_validate(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {"id": "u", "organization": "org-alpha", "roles": ["reader"]},
            "request": {"text": "inspect res-001"},
        }
    )
    assert request_hash(request) == request_hash(request.model_dump())
    assert canonical_json(request).startswith('{"mode"')


def test_rejects_extra_fields_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": {},
                "request": {},
                "extra": True,
            }
        )
    assert datetime.now(UTC).tzinfo is not None


def test_gate_requires_approver_role() -> None:
    with pytest.raises(ValidationError):
        HumanGateDecisionRequest(
            decision="approved", decided_by="a", roles=["reader"], comment="ok"
        )


def test_operational_errors_are_readable_and_old_records_remain_valid() -> None:
    current = operational_error("MODEL_UNAVAILABLE", trace_id="trace-1")
    legacy = ErrorResponse(
        code="LEGACY_ERROR",
        message="LEGACY_ERROR",
        trace_id="trace-2",
    )

    assert current.message == "The model service is unavailable or timed out."
    assert current.category == "external_dependency"
    assert current.retryable is True
    assert "model endpoint" in current.operator_action
    assert legacy.category == "unknown"
    assert legacy.retryable is False


def test_policy_override_invalid_error_code_is_cataloged() -> None:
    """C2 adds `ErrorCode.POLICY_OVERRIDE_INVALID`; it must not fall back to the

    generic default descriptor, or operators get no guidance for a rejected
    (loosening) `runtime.policy_overrides` entry.
    """

    error = operational_error("POLICY_OVERRIDE_INVALID", trace_id="trace-3")

    assert error.category == "configuration"
    assert error.retryable is False
    assert "loosen" in error.message
    assert "startup" in error.operator_action


def test_component_access_error_codes_are_cataloged() -> None:
    """E1: `get_component`'s codes are registered, not "outside the catalog"."""

    generic_message = "The request could not be completed."
    for code in ("APPLICATION_NOT_STARTED", "COMPONENT_NOT_FOUND", "COMPONENT_TYPE_MISMATCH"):
        error = operational_error(code, trace_id="trace-4")
        assert error.message != generic_message
        assert error.category == "configuration"


def test_identity_mismatch_error_code_is_cataloged() -> None:
    """E3: a request whose body disagrees with the authenticated identity is

    rejected with a cataloged code, not a generic one.
    """

    error = operational_error("IDENTITY_MISMATCH", trace_id="trace-5")

    assert error.message != "The request could not be completed."
    assert error.category == "conflict"
