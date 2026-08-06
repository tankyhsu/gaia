from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import (
    ActorType,
    EventStatus,
    ModelCapabilities,
    ModelHealth,
    RunEvent,
    RunRequest,
    RunSnapshot,
    RunStatus,
)
from tests.runtime_capture import CreateCaptureRuntime, capture_api_dependencies


class ApiProjectionRuntime(CreateCaptureRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.runs: dict[str, RunSnapshot] = {}

    async def create(
        self,
        request: RunRequest,
        idempotency_key: str,
    ) -> RunSnapshot:
        snapshot = await super().create(request, idempotency_key)
        snapshot = snapshot.model_copy(update={"status": RunStatus.SUCCEEDED})
        self.runs[snapshot.run_id] = snapshot
        return snapshot

    async def inspect(self, run_id: str) -> RunSnapshot:
        try:
            return self.runs[run_id]
        except KeyError as error:
            raise KeyError(run_id) from error

    async def events_after(
        self,
        run_id: str,
        sequence: int = 0,
    ) -> list[RunEvent]:
        self.runs[run_id]
        if sequence >= 1:
            return []
        return [
            RunEvent(
                event_id=f"{run_id}:1",
                run_id=run_id,
                sequence=1,
                timestamp=datetime.now(UTC),
                actor=ActorType.SYSTEM,
                step="finalize",
                status=EventStatus.SUCCEEDED,
                source_refs=[],
                rule_refs=[],
            )
        ]


def _app(
    tmp_path: Path,
    runtime: ApiProjectionRuntime,
    *,
    config: GaiaApplicationConfig | None = None,
    model_health: AsyncMock | None = None,
):
    dependencies = capture_api_dependencies(runtime)
    if model_health is not None:
        dependencies = dependencies.__class__(
            runtime_factory=dependencies.runtime_factory,
            model_health=model_health,
        )
    return create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db",
        gaia_application=GaiaApplication(config or GaiaApplicationConfig()),
        dependencies=dependencies,
    )


def test_api_create_read_and_events_use_runtime_spi(tmp_path: Path) -> None:
    runtime = ApiProjectionRuntime()
    with TestClient(_app(tmp_path, runtime)) as client:
        response = client.post(
            "/v1/runs",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "Idempotency-Key": "12345678",
            },
            json={
                "scenario_id": "controlled-task",
                "mode": "mock",
                "user": {
                    "id": "u",
                    "organization": "org-alpha",
                    "roles": ["reader"],
                },
                "request": {"text": "inspect res-001"},
            },
        )
        run_id = response.json()["run_id"]
        read = client.get(
            f"/v1/runs/{run_id}",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        events = client.get(
            f"/v1/runs/{run_id}/events",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )

    assert response.status_code == 201
    assert read.status_code == 200
    assert events.status_code == 200
    assert events.json()[-1]["step"] == "finalize"
    assert runtime.idempotency_keys == ["12345678"]


def test_invalid_gate_decision_returns_serializable_validation_error(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path, ApiProjectionRuntime())) as client:
        response = client.post(
            "/v1/human-gates/gate-1/decision",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            json={
                "decision": "approved",
                "decided_by": "manager-1",
                "roles": ["manager"],
                "comment": "Missing the required approver role.",
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert response.json()["details"]["errors"][0]["msg"] == (
        "Value error, roles must contain approver"
    )


def test_readiness_is_not_ready_when_required_model_is_unhealthy(
    tmp_path: Path,
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

    with TestClient(
        _app(tmp_path, ApiProjectionRuntime(), model_health=model_health)
    ) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["model"] == "down"


def test_sandbox_profile_is_server_owned_and_projected(
    tmp_path: Path,
) -> None:
    config = GaiaApplicationConfig(
        runtime={
            "environment": "sandbox",
            "execution": {"provider": "temporal"},
        }
    )
    runtime = ApiProjectionRuntime()
    body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {
            "id": "u",
            "organization": "org-alpha",
            "roles": ["reader"],
        },
        "request": {"text": "inspect res-001"},
    }
    headers = {
        "X-Gaia-Api-Key": "gaia-dev-key",
        "Idempotency-Key": "sandbox-key",
    }

    with TestClient(_app(tmp_path, runtime, config=config)) as client:
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

    assert accepted.status_code == 201
    assert accepted.json()["mode"] == "sandbox"
    assert actuator.json()["config"]["runtime"]["environment"] == "sandbox"
    assert actuator.json()["config"]["runtime"]["write_mode"] == "approval_required"
