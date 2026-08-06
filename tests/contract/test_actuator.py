from pathlib import Path

from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig, SecretRef


def test_actuator_exposes_application_and_protects_details(tmp_path: Path) -> None:
    application = GaiaApplication(
        GaiaApplicationConfig(model={"api_key": SecretRef(file="/private/model-key")})
    )
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/actuator.db",
        api_key="test-key",
        gaia_application=application,
    )

    with TestClient(app) as client:
        info = client.get("/actuator/info")
        health = client.get("/actuator/health")
        unauthorized = client.get("/actuator/components")
        components = client.get("/actuator/components", headers={"X-Gaia-Api-Key": "test-key"})
        config = client.get("/actuator/config", headers={"X-Gaia-Api-Key": "test-key"})
        conditions = client.get("/actuator/conditions", headers={"X-Gaia-Api-Key": "test-key"})
        runtime = client.get("/actuator/runtime", headers={"X-Gaia-Api-Key": "test-key"})

    assert info.status_code == 200
    assert info.json()["application_name"] == "gaia-app"
    assert info.json()["state"] == "started"
    assert info.json()["devtools_enabled"] is False
    assert health.json()["status"] == "UP"
    assert unauthorized.status_code == 401
    assert unauthorized.json()["message"] == "Authentication is missing or invalid."
    assert unauthorized.json()["category"] == "authentication"
    assert unauthorized.json()["retryable"] is False
    assert "API key" in unauthorized.json()["operator_action"]
    assert unauthorized.json()["trace_id"]
    assert {item["kind"] for item in components.json()} >= {
        "model",
        "workflow",
        "context",
        "policy",
        "persistence",
    }
    assert config.json()["config"]["model"]["api_key"] == {"file": "***"}
    assert config.json()["config"]["runtime"]["environment"] == "mock"
    assert config.json()["config"]["runtime"]["write_mode"] == "enabled"
    assert conditions.json()
    assert runtime.status_code == 200
    assert runtime.json()["total_runs"] == 0
    assert runtime.json()["database"]["backend"] == "unconfigured"


def test_framework_api_can_start_without_application_runtime(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite+aiosqlite:///{tmp_path}/framework.db")

    with TestClient(app) as client:
        ready = client.get("/health/ready")
        run = client.get("/v1/runs/missing", headers={"X-Gaia-Api-Key": "gaia-dev-key"})

    assert ready.status_code == 200
    assert ready.json()["checks"]["runtime"] == "not_configured"
    assert run.status_code == 503
    assert run.json()["code"] == "RUNTIME_UNAVAILABLE"
