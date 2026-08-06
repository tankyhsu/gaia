from gaia.contracts.models import ErrorCode
from gaia.runtime.temporal_workflow import (
    _event,
    apply_outcome_to_snapshot,
    build_initial_snapshot,
    command_maximum_attempts,
    command_result_outcome,
    command_result_rule_refs,
    reserve_budget_step,
)


def test_initial_temporal_snapshot_uses_gaia_contract_fields() -> None:
    snapshot = build_initial_snapshot(
        {
            "run_id": "gaia-run-1",
            "issued_at": "2026-07-29T00:00:00+00:00",
            "request": {
                "scenario_id": "ticket.prepare",
                "mode": "mock",
                "user": {
                    "id": "employee-1",
                    "organization": "gaia",
                    "roles": ["employee"],
                },
            },
            "version_bundle": {
                "policy": "policy:1",
                "workflow": "workflow:1",
                "rules": "rules:1",
                "prompt": "prompt:1",
                "model_profile": "model:1",
                "toolset": "tools:1",
                "context_profile": "context:1",
            },
        }
    )

    assert snapshot["run_id"] == "gaia-run-1"
    assert snapshot["scenario_id"] == "ticket.prepare"
    assert snapshot["status"] == "received"
    assert snapshot["version_bundle"]["workflow"] == "workflow:1"


def test_terminal_activity_outcome_updates_temporal_snapshot() -> None:
    snapshot = {
        "run_id": "gaia-run-1",
        "status": "running",
        "updated_at": "2026-07-29T00:00:00+00:00",
    }

    updated = apply_outcome_to_snapshot(
        snapshot,
        {
            "status": "succeeded",
            "result": {"summary": "done"},
            "error_code": None,
        },
        timestamp="2026-07-29T00:01:00+00:00",
    )

    assert updated["status"] == "succeeded"
    assert updated["result"] == {"summary": "done"}
    assert updated["updated_at"] == "2026-07-29T00:01:00+00:00"
    assert snapshot["status"] == "running"


def test_temporal_event_preserves_business_trace_attribution() -> None:
    event = _event(
        run_id="gaia-run-1",
        sequence=3,
        timestamp="2026-07-29T00:01:00+00:00",
        step="load_context",
        status="succeeded",
        actor="tool",
        source_refs=["document-1"],
        rule_refs=["RULE-1"],
    )

    assert event["actor"] == "tool"
    assert event["source_refs"] == ["document-1"]
    assert event["rule_refs"] == ["RULE-1"]


def test_temporal_owns_write_retry_policy_without_a_gaia_recovery_loop() -> None:
    assert (
        command_maximum_attempts(
            {"recovery_strategy": "idempotent", "max_retries": 1}
        )
        == 2
    )
    assert (
        command_maximum_attempts(
            {"recovery_strategy": "at_most_once_manual", "max_retries": 1}
        )
        == 1
    )


def test_unknown_write_result_blocks_for_operator_attention() -> None:
    outcome = command_result_outcome(
        {
            "ok": False,
            "status": "unknown",
            "data": {},
            "error_code": ErrorCode.SIDE_EFFECT_UNKNOWN.value,
        },
        recovery_strategy="reconcilable",
    )

    assert outcome == {
        "status": "blocked",
        "result": None,
        "error_code": "SIDE_EFFECT_UNKNOWN",
    }


def test_unknown_write_result_carries_uncertainty_rule_refs() -> None:
    assert command_result_rule_refs(
        {"uncertainty_rule_refs": ["RULE-UNKNOWN"]},
        {"error_code": "SIDE_EFFECT_UNKNOWN"},
    ) == ["RULE-UNKNOWN"]
    assert (
        command_result_rule_refs(
            {"uncertainty_rule_refs": ["RULE-UNKNOWN"]},
            {"error_code": None},
        )
        == []
    )


def test_command_step_is_reserved_in_workflow_budget() -> None:
    budget = {"max_steps": 2, "steps_used": 1}

    assert reserve_budget_step(budget) is True
    assert budget["steps_used"] == 2
    assert reserve_budget_step(budget) is False


def test_command_step_without_configured_budget_is_unbounded() -> None:
    assert reserve_budget_step({}) is True
