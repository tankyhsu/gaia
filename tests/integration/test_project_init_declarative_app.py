"""``gaia init`` selects local or Temporal execution from the scenario template."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gaia.application import GaiaApplication
from gaia.runtime.in_process_runtime import InProcessRuntimeEngine
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.templates import project_files, python_module_name, selected_starters


def _write_project(tmp_path: Path, name: str, template_id: str) -> tuple[Path, str]:
    module_name = python_module_name(name)
    for relative, contents in project_files(
        name,
        selected_starters(template_id),
        template_id=template_id,
    ).items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return tmp_path, module_name


@pytest.mark.parametrize("template_id", ["basic", "knowledge", "approval"])
def test_generated_gaia_yaml_declares_scenario_runtime(
    tmp_path: Path,
    template_id: str,
) -> None:
    root, module_name = _write_project(tmp_path, "declarative-app", template_id)
    scenario_suffix = {
        "basic": "hello",
        "knowledge": "knowledge",
        "approval": "approval",
    }[template_id]

    gaia_yaml = (root / "gaia.yaml").read_text(encoding="utf-8")

    assert "scenario-runtime" in gaia_yaml
    assert "scenarios:" in gaia_yaml
    assert "modules:" in gaia_yaml
    assert f"{module_name}.scenarios.{scenario_suffix}" in gaia_yaml


@pytest.mark.parametrize("template_id", ["basic", "knowledge", "approval"])
def test_generated_app_has_no_manual_runtime_assembly(
    tmp_path: Path,
    template_id: str,
) -> None:
    root, module_name = _write_project(tmp_path, "declarative-app", template_id)
    app_py = (root / f"src/{module_name}/app.py").read_text(encoding="utf-8")

    assert "GaiaAppBuilder" not in app_py
    assert "dependencies=" not in app_py
    assert "get_component(" not in app_py
    assert len([line for line in app_py.splitlines() if line.strip()]) <= 15


def _boot_generated_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    template_id: str,
) -> FastAPI:
    root, module_name = _write_project(tmp_path, name, template_id)
    monkeypatch.syspath_prepend(str(root / "src"))
    monkeypatch.setenv("GAIA_CONFIG_PATH", str(root / "gaia.yaml"))
    monkeypatch.setenv(
        "GAIA__RUNTIME__DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
    )
    app_module = importlib.import_module(f"{module_name}.app")
    application: FastAPI = app_module.create_application()
    return application


@pytest.mark.parametrize(
    ("template_id", "name", "runtime_type"),
    [
        ("basic", "declarative-basic", InProcessRuntimeEngine),
        ("approval", "declarative-approval", TemporalRuntimeEngine),
    ],
)
def test_generated_app_selects_runtime_for_scenario_requirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template_id: str,
    name: str,
    runtime_type: type[object],
) -> None:
    app = _boot_generated_app(tmp_path, monkeypatch, name, template_id)

    with TestClient(app) as client:
        ready = client.get(
            "/health/ready",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        runtime = app.state.runtime

    assert ready.status_code == 200
    assert isinstance(runtime, runtime_type)


def test_generated_basic_app_completes_an_in_process_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _boot_generated_app(tmp_path, monkeypatch, "declarative-basic-run", "basic")

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "Idempotency-Key": "generated-basic-in-process-001",
            },
            json={
                "scenario_id": "hello",
                "mode": "mock",
                "user": {
                    "id": "developer",
                    "organization": "example",
                    "roles": ["user"],
                },
                "request": {"text": "Gaia"},
            },
        )

        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "succeeded"
        assert run["result"]["message"] == "Hello, Gaia"

        events = client.get(
            f"/v1/runs/{run['run_id']}/events",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        assert events.status_code == 200
        assert events.json()[0]["details"]["provider"] == "in_process"


def test_generated_knowledge_app_configures_rag_and_runtime_assembler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _module_name = _write_project(
        tmp_path,
        "declarative-knowledge",
        "knowledge",
    )
    monkeypatch.syspath_prepend(str(root / "src"))
    application = GaiaApplication.from_config(root / "gaia.yaml")

    context = asyncio.run(application.configure())

    component_ids = {item.component_id for item in context.descriptors}
    assert "runtime-assembler" in component_ids
    assert "rag-postgres" in component_ids


@pytest.fixture(autouse=True)
def _isolate_generated_packages() -> Iterator[None]:
    known_before = set(sys.modules)
    yield
    for name in list(sys.modules):
        if name not in known_before and name.startswith("declarative_"):
            del sys.modules[name]
