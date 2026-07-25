from pathlib import Path

from fastapi.testclient import TestClient

from examples.controlled_task.app import create_app


def test_runtime_summary_explains_success_waiting_and_contention(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/observability.db"
    api_headers = {"X-Gaia-Api-Key": "gaia-dev-key"}
    user = {"id": "u", "organization": "org-alpha", "roles": ["operator"]}

    with TestClient(create_app(database_url)) as client:
        succeeded = client.post(
            "/v1/runs",
            headers={**api_headers, "Idempotency-Key": "summary-success"},
            json={
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": user,
                "request": {"text": "inspect res-001"},
            },
        )
        waiting = client.post(
            "/v1/runs",
            headers={**api_headers, "Idempotency-Key": "summary-waiting"},
            json={
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": user,
                "request": {"text": "pause res-001 because maintenance"},
            },
        )
        response = client.get(
            "/actuator/runtime?window_hours=24&stale_after_seconds=30",
            headers=api_headers,
        )

    assert succeeded.status_code == 201
    assert waiting.status_code == 201
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_runs"] == 2
    assert summary["status_counts"]["succeeded"] == 1
    assert summary["status_counts"]["waiting_human"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["failure_rate"] == 0.0
    assert summary["pending_human_gates"] == 1
    assert summary["oldest_pending_gate_age_seconds"] is not None
    assert summary["run_duration"]["p95_ms"] is not None
    assert summary["database"]["backend"] == "sqlite"
    assert summary["outbox"]["pending"] == 0
    assert summary["issues"][0]["run_id"] == waiting.json()["run_id"]
    assert summary["issues"][0]["bottleneck"] == "human_gate"
