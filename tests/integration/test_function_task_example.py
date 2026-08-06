"""Composition contracts for the declarative ``function_task`` example."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from examples.function_task.app import build
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
