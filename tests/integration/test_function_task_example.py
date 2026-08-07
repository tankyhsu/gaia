"""Composition contracts for the declarative ``function_task`` example."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from examples.function_task.app import build
from examples.function_task.flows import reject_request
from examples.function_task.tools import lookup_resource, publish_resource
from gaia import ScenarioContext, get_tool_spec
from gaia.contracts.models import RunMode, RunRequest, RunStatus
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_PY = _REPO_ROOT / "examples" / "function_task" / "app.py"


def test_example_starts_with_temporal_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "GAIA__RUNTIME__DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'function-task.db'}",
    )
    app = build()

    with TestClient(app) as client:
        ready = client.get(
            "/health/ready",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        runtime = app.state.runtime

    assert ready.status_code == 200
    assert isinstance(runtime, TemporalRuntimeEngine)
    assert [handler.__name__ for handler in runtime.activity_handlers()] == [
        "run_scenario",
        "execute_command",
        "record_audit",
    ]


def test_app_py_stays_a_thin_composition_root() -> None:
    non_empty_lines = [line for line in _APP_PY.read_text().splitlines() if line.strip()]
    assert len(non_empty_lines) <= 15, (
        "examples/function_task/app.py must contain no manual runtime assembly; "
        f"found {len(non_empty_lines)} non-empty lines"
    )


def test_app_honors_the_canonical_config_override(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  application:\n"
        "    name: overridden-function-task\n"
        "  profile: mock\n"
        "  starters:\n"
        "    - core-runtime\n"
        "    - model-mock\n"
        "    - scenario-runtime\n"
        "  scenarios:\n"
        "    modules:\n"
        "      - examples.function_task.flows\n"
        "      - examples.function_task.tools\n"
    )
    monkeypatch.setenv("GAIA_CONFIG_PATH", str(config))

    app = build()

    with TestClient(app):
        assert app.state.gaia_application.config.application.name == (
            "overridden-function-task"
        )


async def test_demo_policy_refusal_is_terminal_and_has_no_side_effect() -> None:
    request = RunRequest.model_validate(
        {
            "scenario_id": "function_task.reject_request",
            "mode": "mock",
            "user": {"id": "demo", "organization": "demo", "roles": ["user"]},
            "request": {"text": "demonstrate a policy refusal"},
        }
    )

    response = await reject_request(ScenarioContext(run_id="run-demo", request=request))

    assert response.status == RunStatus.BLOCKED
    assert response.side_effect is None
    assert response.decision_rule_refs == ("RULE-FUNCTION-TASK-DENY",)


def test_reference_tools_are_explicitly_safe_for_mock_and_sandbox() -> None:
    expected = [RunMode.MOCK, RunMode.SANDBOX]

    assert get_tool_spec(lookup_resource).definition.allowed_environments == expected
    assert get_tool_spec(publish_resource).definition.allowed_environments == expected
