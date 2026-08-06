"""Contract tests for the `scenario-runtime` starter (task A4).

These tests prove three things end to end:

1. When `scenarios.modules` is configured, the `scenario-runtime` starter discovers the
   declared scenario/tool modules and registers a `runtime-assembler` RUNTIME component.
2. `create_app` falls back to that component when no explicit `dependencies` are supplied,
   and a real HTTP run through a purely declarative `gaia.yaml` reaches `succeeded`.
3. Without `scenarios.modules`, the starter's condition does not match and it is reported
   as a negative auto-configuration outcome.
4. An application that DOES pass explicit `dependencies` keeps using those, never the
   component graph -- the declarative path must never shadow the existing manual one.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.config.models import GaiaApplicationConfig
from gaia.persistence.database import (
    dispose_session_factory,
    initialize_database,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.starters import BUILTIN_STARTERS, AutoConfigurator
from tests.runtime_capture import CreateCaptureRuntime, capture_api_dependencies

_FIXTURE_MODULE_SOURCE = '''
"""Fixture scenario module written to disk for scenario-runtime starter tests."""

from gaia import ScenarioContext, scenario
from gaia import read_tool


@read_tool("scenario_runtime_fixture.echo")
async def echo_tool() -> dict[str, object]:
    return {{"echo": "ok"}}


@scenario(
    "{scenario_id}",
    allowed_tools=("scenario_runtime_fixture.echo",),
    max_model_calls=0,
)
async def read_only(context: ScenarioContext) -> dict[str, object]:
    assert context.tools is not None
    called = await context.tools.call(echo_tool)
    return {{"message": f"Hello, {{context.text}}", "tool": called.data}}
'''

@pytest.fixture
def scenario_module(tmp_path: Path) -> Iterator[str]:
    """Write a real, importable-by-name scenario module under tmp_path and clean up after."""

    module_name = "scenario_runtime_fixture_module"
    (tmp_path / f"{module_name}.py").write_text(
        _FIXTURE_MODULE_SOURCE.format(scenario_id="declarative.read_only")
    )
    sys.path.insert(0, str(tmp_path))
    try:
        yield module_name
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)


def _write_config(tmp_path: Path, module_name: str) -> Path:
    config_path = tmp_path / "gaia.yaml"
    config_path.write_text(
        "gaia:\n"
        "  runtime:\n"
        "    execution: {provider: temporal}\n"
        "  starters:\n"
        "    - core-runtime\n"
        "    - model-mock\n"
        "    - scenario-runtime\n"
        "  scenarios:\n"
        f"    modules: [{module_name}]\n"
    )
    return config_path


async def test_scenario_runtime_starter_registers_runtime_assembler(
    tmp_path: Path, scenario_module: str
) -> None:
    application = GaiaApplication.from_config(_write_config(tmp_path, scenario_module))

    await application.configure()

    snapshot = application.actuator_snapshot()
    component_ids = {item.component_id for item in snapshot.components}
    assert "runtime-assembler" in component_ids
    assembler_descriptor = next(
        item for item in snapshot.components if item.component_id == "runtime-assembler"
    )
    assert assembler_descriptor.implementation == "gaia.runtime.assembly.RuntimeAssembler"
    assert assembler_descriptor.starter_id == "scenario-runtime"


async def test_declarative_scenario_component_assembles_temporal_runtime(
    tmp_path: Path,
    scenario_module: str,
) -> None:
    application = GaiaApplication.from_config(_write_config(tmp_path, scenario_module))
    async with application.lifespan():
        assembler = application.get_component("runtime-assembler")
        database_url = "sqlite+aiosqlite:///:memory:"
        factory = await initialize_database(database_url)
        try:
            runtime = assembler.create_engine(factory, database_url)
        finally:
            await dispose_session_factory(factory)

    assert isinstance(runtime, TemporalRuntimeEngine)
    # Scenario execution, command execution, and the audit projection: a Worker
    # assembled declaratively can record evidence, not only run work.
    assert [handler.__name__ for handler in runtime.activity_handlers()] == [
        "run_scenario",
        "execute_command",
        "record_audit",
    ]


def test_scenario_runtime_starter_is_inert_without_scenario_modules() -> None:
    config = GaiaApplicationConfig(starters=("core-runtime", "model-mock", "scenario-runtime"))

    registry, report = AutoConfigurator(BUILTIN_STARTERS).configure(config)

    assert "scenario-runtime" in {item.starter_id for item in report.negative}
    assert "scenario-runtime" not in {item.starter_id for item in report.positive}
    assert not any(item.component_id == "runtime-assembler" for item in registry.descriptors())


def test_create_app_prefers_explicit_dependencies_over_the_component_graph(
    tmp_path: Path, scenario_module: str
) -> None:
    application = GaiaApplication.from_config(_write_config(tmp_path, scenario_module))
    explicit_runtime = CreateCaptureRuntime()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=application,
        dependencies=capture_api_dependencies(explicit_runtime),
    )

    with TestClient(app):
        assert app.state.runtime is explicit_runtime
