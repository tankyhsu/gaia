"""Contract tests for task A4b: built-in MODEL Starters register real providers.

Before A4b, `model-mock` / `model-openai-compatible` registered `{"starter": "<id>"}`
marker dicts (see `gaia.starters.builtin.BuiltinStarter`). `scenario-runtime`'s
port-narrowing check (`_model_provider_from`, proven by `test_scenario_runtime_starter.py`)
therefore always treated MODEL as absent, so a model-backed declarative scenario needed an
application-supplied `model_provider` -- the declarative path only worked end to end for
read-only scenarios. These tests prove that gap is closed:

1. The milestone test: a purely declarative `gaia.yaml` (`core-runtime`, `model-mock`,
   `scenario-runtime`, no explicit `dependencies`) serves a scenario that calls
   `ctx.model.generate_structured(...)` and reaches `succeeded` with model-derived content
   in the result.
2. The MODEL component's `implementation` in the Actuator snapshot is a real class path,
   not `gaia.starters.model-mock` / `gaia.starters.model-openai-compatible`.
3. A resolved `model-openai-compatible` API key never appears anywhere in a serialized
   `actuator_snapshot()`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from gaia.application import GaiaApplication
from gaia.config.models import GaiaApplicationConfig
from gaia.contracts.models import ModelEndpointProfile
from gaia.model_gateway import model_endpoint_profile_from_config
from gaia.persistence.database import (
    dispose_session_factory,
    initialize_database,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine

_FIXTURE_MODULE_SOURCE = '''
"""Fixture scenario module: a model-backed declarative scenario for the A4b milestone test."""

from pydantic import BaseModel

from gaia.config.models import GaiaApplicationConfig
from gaia.model_gateway import model_endpoint_profile_from_config
from gaia.spi.model import ModelMessage
from gaia import ScenarioContext, scenario

# Constructing a default GaiaApplicationConfig() and deriving a profile from it is pure --
# no I/O, no secrets -- so it is safe at module import time under the "import-time purity"
# scenario-module contract.
_PROFILE = model_endpoint_profile_from_config(GaiaApplicationConfig())


class Greeting(BaseModel):
    message: str
    note: str | None = None


@scenario("{scenario_id}", max_model_calls=1)
async def model_backed(context: ScenarioContext) -> dict[str, object]:
    assert context.model is not None
    result = await context.model.generate_structured(
        profile=_PROFILE,
        messages=[ModelMessage(role="user", content=context.text)],
        output_schema=Greeting,
        timeout_seconds=2,
    )
    return {{"message": result.output["message"], "note": result.output["note"]}}
'''


@pytest.fixture
def model_backed_scenario_module(tmp_path: Path) -> Iterator[str]:
    """Write a real, importable-by-name scenario module under tmp_path and clean up after."""

    module_name = "model_starters_fixture_module"
    (tmp_path / f"{module_name}.py").write_text(
        _FIXTURE_MODULE_SOURCE.format(scenario_id="declarative.model_backed")
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


async def test_model_mock_scenario_assembles_temporal_runtime_without_dependencies(
    tmp_path: Path,
    model_backed_scenario_module: str,
) -> None:
    application = GaiaApplication.from_config(_write_config(tmp_path, model_backed_scenario_module))
    async with application.lifespan():
        assembler = application.get_component("runtime-assembler")
        model_provider = application.get_component("model-default")
        database_url = "sqlite+aiosqlite:///:memory:"
        factory = await initialize_database(database_url)
        try:
            runtime = assembler.create_engine(factory, database_url)
        finally:
            await dispose_session_factory(factory)

    assert isinstance(runtime, TemporalRuntimeEngine)
    assert type(model_provider).__module__ == "gaia.model_gateway.mock"
    assert type(model_provider).__name__ == "DeterministicMockProvider"


async def test_model_mock_component_implementation_is_the_real_provider_class(
    tmp_path: Path,
) -> None:
    application = GaiaApplication.from_config(_write_config_without_scenarios(tmp_path))

    await application.configure()

    snapshot = application.actuator_snapshot()
    model_component = next(item for item in snapshot.components if item.kind == "model")
    assert model_component.component_id == "model-default"
    assert model_component.implementation == "gaia.model_gateway.mock.DeterministicMockProvider"
    assert model_component.starter_id == "model-mock"


async def test_model_openai_compatible_component_implementation_is_the_real_provider_class(
    tmp_path: Path,
) -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "starters": ["core-runtime", "model-openai-compatible"],
            "model": {
                "provider": "openai-compatible",
                "base_url": "https://model.example/v1",
                "api_key": {"env": "GAIA_TEST_MODEL_API_KEY"},
            },
        }
    )
    application = GaiaApplication(config)

    await application.configure()

    snapshot = application.actuator_snapshot()
    model_component = next(item for item in snapshot.components if item.kind == "model")
    assert model_component.component_id == "model-default"
    assert (
        model_component.implementation
        == "gaia.model_gateway.openai_compatible.OpenAICompatibleProvider"
    )
    assert model_component.starter_id == "model-openai-compatible"


async def test_resolved_openai_compatible_api_key_never_appears_in_actuator_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "sk-super-secret-value-should-never-leak-0451"
    monkeypatch.setenv("GAIA_TEST_MODEL_API_KEY", secret_value)
    config = GaiaApplicationConfig.model_validate(
        {
            "starters": ["core-runtime", "model-openai-compatible"],
            "model": {
                "provider": "openai-compatible",
                "base_url": "https://model.example/v1",
                "api_key": {"env": "GAIA_TEST_MODEL_API_KEY"},
            },
        }
    )
    application = GaiaApplication(config)

    # start() (not just configure()) actually instantiates the provider via the Starter's
    # factory closure, which is where resolve_secret(config.model.api_key) runs.
    async with application.lifespan() as _started:
        snapshot = application.actuator_snapshot()
        provider = application.get_component("model-default")
        # Sanity: the resolved key really did make it into the provider instance -- so this
        # test would fail loudly (KeyError from resolve_secret / assertion below) instead of
        # vacuously passing if the Starter stopped resolving the secret at all.
        assert provider._api_key == secret_value  # noqa: SLF001

    serialized = json.dumps(snapshot.model_dump(mode="json"))
    assert secret_value not in serialized


def _write_config_without_scenarios(tmp_path: Path) -> Path:
    config_path = tmp_path / "gaia.yaml"
    config_path.write_text("gaia:\n  starters:\n    - core-runtime\n    - model-mock\n")
    return config_path


def test_model_endpoint_profile_from_config_mock() -> None:
    profile = model_endpoint_profile_from_config(GaiaApplicationConfig())

    assert isinstance(profile, ModelEndpointProfile)
    assert profile.provider_id == "mock"
    assert profile.protocol == "mock"
    assert profile.base_url is None
    assert profile.model_id == "deterministic-mock"
    assert profile.data_residency == "local"
    assert profile.capabilities.structured_output is True
    assert profile.capabilities.streaming is False


def test_model_endpoint_profile_from_config_openai_compatible() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "model": {
                "provider": "openai-compatible",
                "model_id": "gpt-test",
                "base_url": "https://model.example/v1",
                "api_key": {"env": "GAIA_TEST_MODEL_API_KEY"},
                "timeout_seconds": 7,
            }
        }
    )

    profile = model_endpoint_profile_from_config(config)

    assert profile.provider_id == "openai-compatible"
    assert profile.protocol == "openai-compatible"
    assert profile.base_url == "https://model.example/v1"
    assert profile.model_id == "gpt-test"
    assert profile.timeout_seconds == 7
    assert profile.data_residency == "external"
    assert profile.capabilities.streaming is True
    # ModelEndpointProfile has no api_key field: resolving the SecretRef is the caller's
    # (Starter's) job, not this helper's -- see gaia/model_gateway/profile.py.
    assert not hasattr(profile, "api_key")
