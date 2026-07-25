from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from examples.controlled_task.app import create_app
from gaia.contracts.models import ModelCapabilities, ModelHealth
from gaia.runtime.persistent_engine import PersistentRuntimeEngine


def test_api_creates_and_reads_run(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    with TestClient(create_app(database_url)) as client:
        response = client.post(
            "/v1/runs",
            headers={"X-Gaia-Api-Key": "gaia-dev-key", "Idempotency-Key": "12345678"},
            json={
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": {"id": "u", "organization": "org-alpha", "roles": ["reader"]},
                "request": {"text": "inspect res-001"},
            },
        )
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        assert (
            client.get(f"/v1/runs/{run_id}", headers={"X-Gaia-Api-Key": "gaia-dev-key"}).status_code
            == 200
        )
        events = client.get(f"/v1/runs/{run_id}/events", headers={"X-Gaia-Api-Key": "gaia-dev-key"})
        assert events.status_code == 200
        assert events.json()[-1]["step"] == "finalize"
        observations = client.get(
            f"/v1/runs/{run_id}/model-invocations",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        assert observations.status_code == 200
        assert observations.json()["summary"]["total"] == 1
        invocation = observations.json()["invocations"][0]
        assert invocation["run_id"] == run_id
        assert invocation["model_id"] == "deterministic-mock"
        assert invocation["status"] == "succeeded"
        assert "inspect res-001" not in observations.text
        guardrails = client.get(
            f"/v1/runs/{run_id}/guardrail-decisions",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        assert guardrails.status_code == 200
        assert guardrails.json()["summary"]["total"] == 0


def test_readiness_reports_startup_recovery_without_rerunning_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    startup_recover = AsyncMock(return_value=["run-recovered"])
    monkeypatch.setattr(PersistentRuntimeEngine, "startup_recover", startup_recover)
    database_url = f"sqlite+aiosqlite:///{tmp_path}/ready.db"

    with TestClient(create_app(database_url)) as client:
        first = client.get("/health/ready")
        second = client.get("/health/ready")

    assert first.status_code == 200
    assert first.json()["checks"]["startup_recovery_runs"] == "1"
    assert second.status_code == 200
    assert startup_recover.await_count == 1


def test_readiness_is_not_ready_when_required_model_is_unhealthy(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    model_health = AsyncMock(
        return_value=ModelHealth(
            provider_id="mock",
            model_id="deterministic-mock",
            healthy=False,
            capabilities=ModelCapabilities(
                structured_output=True,
                tool_calling=False,
                streaming=False,
                max_context_tokens=1024,
            ),
            checked_at=datetime.now(UTC),
            error_code="MODEL_UNAVAILABLE",
        )
    )
    monkeypatch.setattr(
        "examples.controlled_task.app.DeterministicMockProvider.health",
        model_health,
    )

    with TestClient(create_app(f"sqlite+aiosqlite:///{tmp_path}/model-unhealthy.db")) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["model"] == "down"


def test_replay_endpoint_runs_selected_case(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/replay.db"
    with TestClient(create_app(database_url)) as client:
        response = client.post(
            "/v1/evals/replays",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            json={"case_ids": ["case-01"]},
        )
    assert response.status_code == 201
    assert response.json()["total"] == 1
    assert response.json()["passed"] == 1
    assert response.json()["failed"] == 0
    assert response.json()["results"][0]["case_id"] == "case-01"


def test_sandbox_profile_is_server_owned_and_requires_matching_run_mode(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("GAIA__PROFILE", "sandbox")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/sandbox.db"
    headers = {"X-Gaia-Api-Key": "gaia-dev-key", "Idempotency-Key": "sandbox-key"}
    body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "u", "organization": "org-alpha", "roles": ["reader"]},
        "request": {"text": "inspect res-001"},
    }

    with TestClient(create_app(database_url)) as client:
        mismatch = client.post("/v1/runs", headers=headers, json=body)
        body["mode"] = "sandbox"
        accepted = client.post(
            "/v1/runs",
            headers={**headers, "Idempotency-Key": "sandbox-key-accepted"},
            json=body,
        )
        actuator = client.get(
            "/actuator/config",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )

    assert mismatch.status_code == 403
    assert mismatch.json()["code"] == "ENVIRONMENT_MODE_MISMATCH"
    assert accepted.status_code == 201
    assert accepted.json()["mode"] == "sandbox"
    assert actuator.status_code == 200
    assert actuator.json()["config"]["runtime"]["environment"] == "sandbox"
    assert actuator.json()["config"]["runtime"]["write_mode"] == "approval_required"
