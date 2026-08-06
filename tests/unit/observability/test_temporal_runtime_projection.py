from datetime import UTC, datetime

from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import RunPage, RunSnapshot
from gaia.observability.runtime import RuntimeObservabilityService
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine


class ProjectionRuntime(TemporalRuntimeEngine):
    def __init__(self, runs: list[RunSnapshot]) -> None:
        super().__init__(execution=RuntimeExecutionSettings(provider="temporal"))
        self._runs = runs

    async def list_runs(self, **kwargs: object) -> RunPage:
        del kwargs
        return RunPage(items=self._runs)


async def test_temporal_runtime_summary_is_projected_without_gaia_run_rows() -> None:
    now = datetime.now(UTC)
    run = RunSnapshot.model_validate(
        {
            "run_id": "run-1",
            "trace_id": "0123456789abcdef0123456789abcdef",
            "scenario_id": "ticket.prepare",
            "mode": "mock",
            "status": "waiting_human",
            "user": {
                "id": "employee-1",
                "organization": "gaia",
                "roles": ["employee"],
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
            "pending_gate_id": "run-1:gate:write-1",
            "created_at": now,
            "updated_at": now,
        }
    )

    summary = await RuntimeObservabilityService(
        ProjectionRuntime([run])
    ).summary(window_hours=24, stale_after_seconds=300)

    assert summary.total_runs == 1
    assert summary.pending_human_gates == 1
    assert summary.database.backend == "temporal"
    assert summary.database.pool_class == "TemporalVisibility"
    assert summary.issues[0].trace_id == run.trace_id


def _terminal_run(run_id: str, *, status: str, error_code: str | None) -> RunSnapshot:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "run_id": run_id,
        "scenario_id": "ticket.prepare",
        "mode": "mock",
        "status": status,
        "user": {"id": "employee-1", "organization": "gaia", "roles": ["employee"]},
        "version_bundle": {
            "policy": "policy:1",
            "workflow": "workflow:1",
            "rules": "rules:1",
            "prompt": "prompt:1",
            "model_profile": "model:1",
            "toolset": "tools:1",
            "context_profile": "context:1",
        },
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if error_code is not None:
        payload["error"] = {
            "code": error_code,
            "message": error_code,
            "trace_id": run_id,
            "category": "policy",
            "retryable": False,
            "operator_action": "-",
            "details": {},
        }
    return RunSnapshot.model_validate(payload)


async def test_a_control_refusing_a_run_is_not_reported_as_work_to_do() -> None:
    """An approver saying no is the product working, not a fault.

    The operations view used to headline 成功率 and queue every `blocked` Run
    under 需要处理 as a 运行错误 -- so three demo Runs, two of them correctly
    refused, read as "成功率 33.3%" with two errors waiting. That tells a
    reader the opposite of what happened.
    """

    service = RuntimeObservabilityService(
        ProjectionRuntime(
            [
                _terminal_run("run-ok", status="succeeded", error_code=None),
                _terminal_run(
                    "run-rejected", status="blocked", error_code="HUMAN_GATE_REJECTED"
                ),
                _terminal_run("run-denied", status="blocked", error_code="FORBIDDEN"),
                _terminal_run("run-broken", status="failed", error_code="INTERNAL_ERROR"),
            ]
        )
    )

    summary = await service.summary(window_hours=24, stale_after_seconds=900)

    assert summary.stopped_by_control == 2
    assert summary.status_counts["succeeded"] == 1
    assert summary.status_counts["failed"] == 1
    # The two refusals must not appear as work an operator has to pick up; the
    # genuine failure still must.
    queued = {issue.run_id for issue in summary.issues}
    assert queued == {"run-broken"}


async def test_a_run_that_actually_broke_is_still_queued_for_an_operator() -> None:
    """The rule must not swallow real faults: only refusals are excluded."""

    service = RuntimeObservabilityService(
        ProjectionRuntime(
            [
                _terminal_run(
                    "run-unknown", status="blocked", error_code="SIDE_EFFECT_UNKNOWN"
                )
            ]
        )
    )

    summary = await service.summary(window_hours=24, stale_after_seconds=900)

    # `SIDE_EFFECT_UNKNOWN` is blocked too, but nobody refused it -- the write's
    # true outcome is unknown, which is exactly what needs a human.
    assert summary.stopped_by_control == 0
    assert {issue.run_id for issue in summary.issues} == {"run-unknown"}
