from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from gaia import (
    ScenarioContext,
    ScenarioResponse,
    agent_handler,
    continuation_handler,
    read_tool,
    scenario,
)
from gaia.starters.scenario_discovery import ScenarioDiscoveryError, discover_scenarios


@pytest.fixture
def fake_modules() -> Iterator[list[str]]:
    """Track fake module names registered in sys.modules and remove them afterward."""

    names: list[str] = []
    try:
        yield names
    finally:
        for name in names:
            sys.modules.pop(name, None)


def _register_module(fake_modules: list[str], name: str) -> ModuleType:
    module = ModuleType(name)
    sys.modules[name] = module
    fake_modules.append(name)
    return module


def _attach(module: ModuleType, attr_name: str, handler: Any) -> None:
    handler.__module__ = module.__name__
    setattr(module, attr_name, handler)


def test_discover_scenarios_from_two_modules_is_deterministic(
    fake_modules: list[str],
) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_mod_zeta")
    mod_b = _register_module(fake_modules, "discovery_test_mod_alpha")

    @scenario("zeta.scenario")
    async def scenario_zeta(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @read_tool("zeta.tool")
    async def tool_zeta() -> dict[str, object]:
        return {}

    @scenario("alpha.scenario")
    async def scenario_alpha(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @read_tool("alpha.tool")
    async def tool_alpha() -> dict[str, object]:
        return {}

    _attach(mod_a, "scenario_zeta", scenario_zeta)
    _attach(mod_a, "tool_zeta", tool_zeta)
    _attach(mod_b, "scenario_alpha", scenario_alpha)
    _attach(mod_b, "tool_alpha", tool_alpha)

    result = discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert [spec.scenario_id for spec in result.scenarios] == [
        "alpha.scenario",
        "zeta.scenario",
    ]
    assert result.scenario_handlers == (scenario_alpha, scenario_zeta)
    assert result.tool_handlers == (tool_alpha, tool_zeta)


def test_discover_scenarios_module_not_found(fake_modules: list[str]) -> None:
    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios(("this_module_does_not_exist_anywhere",))

    assert excinfo.value.code == "SCENARIO_MODULE_NOT_FOUND"
    assert excinfo.value.detail == "this_module_does_not_exist_anywhere"


def test_discover_scenarios_absent_parent_package_is_module_not_found(
    fake_modules: list[str],
) -> None:
    # The declared module is "absent_parent_pkg.submodule"; Python resolves the parent
    # package first and fails with ModuleNotFoundError(name="absent_parent_pkg") -- that
    # still means the declared module itself cannot be found, not a transitive dependency
    # problem inside an existing module.
    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios(("absent_parent_pkg_zzz.submodule",))

    assert excinfo.value.code == "SCENARIO_MODULE_NOT_FOUND"
    assert excinfo.value.detail == "absent_parent_pkg_zzz.submodule"


def test_discover_scenarios_transitive_import_error_is_not_misattributed(
    tmp_path: Path, fake_modules: list[str]
) -> None:
    # The declared module genuinely exists on disk; it is one of ITS OWN imports that is
    # missing. This must be reported as SCENARIO_MODULE_IMPORT_FAILED naming both the
    # declared module and the missing dependency, not SCENARIO_MODULE_NOT_FOUND (which would
    # send an operator to edit scenarios.modules for no reason).
    module_name = "discovery_test_bad_dependency"
    (tmp_path / f"{module_name}.py").write_text(
        "import definitely_not_installed_dependency_zzz\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(ScenarioDiscoveryError) as excinfo:
            discover_scenarios((module_name,))
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)

    assert excinfo.value.code == "SCENARIO_MODULE_IMPORT_FAILED"
    assert module_name in excinfo.value.detail
    assert "definitely_not_installed_dependency_zzz" in excinfo.value.detail


def test_discover_scenarios_rejects_duplicate_scenario_id(
    fake_modules: list[str],
) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_dup_scenario_a")
    mod_b = _register_module(fake_modules, "discovery_test_dup_scenario_b")

    @scenario("duplicate.scenario")
    async def scenario_one(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @scenario("duplicate.scenario")
    async def scenario_two(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    _attach(mod_a, "scenario_one", scenario_one)
    _attach(mod_b, "scenario_two", scenario_two)

    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert excinfo.value.code == "SCENARIO_DUPLICATE"
    assert excinfo.value.detail == "duplicate.scenario"


def test_discover_scenarios_rejects_duplicate_tool_name(
    fake_modules: list[str],
) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_dup_tool_a")
    mod_b = _register_module(fake_modules, "discovery_test_dup_tool_b")

    @read_tool("duplicate.tool")
    async def tool_one() -> dict[str, object]:
        return {}

    @read_tool("duplicate.tool")
    async def tool_two() -> dict[str, object]:
        return {}

    _attach(mod_a, "tool_one", tool_one)
    _attach(mod_b, "tool_two", tool_two)

    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert excinfo.value.code == "SCENARIO_TOOL_DUPLICATE"
    assert excinfo.value.detail == "duplicate.tool"


def test_discover_scenarios_does_not_double_count_reexported_scenario(
    fake_modules: list[str],
) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_reexport_owner")
    mod_b = _register_module(fake_modules, "discovery_test_reexport_importer")

    @scenario("owned.scenario")
    async def scenario_owned(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    # Defined and owned by mod_a: __module__ stays mod_a's name.
    _attach(mod_a, "scenario_owned", scenario_owned)
    # mod_b merely imports/re-exports the same object under a local name; its
    # __module__ still points at mod_a, so it must not be collected again.
    mod_b.scenario_owned = scenario_owned

    result = discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert [spec.scenario_id for spec in result.scenarios] == ["owned.scenario"]
    assert result.scenario_handlers == (scenario_owned,)


def test_discover_scenarios_finds_agent_and_continuation_handlers_and_routes(
    fake_modules: list[str],
) -> None:
    mod = _register_module(fake_modules, "discovery_test_agent_and_continuation")

    @scenario(
        "handoff.scenario",
        max_model_calls=0,
        allowed_handoffs=("triage",),
    )
    async def handoff_scenario(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.handoff_to("triage", input={}, reason="route to triage")

    @agent_handler("triage", allowed_handoffs=("specialist",))
    async def triage(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @agent_handler("specialist")
    async def specialist(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @continuation_handler("after-write")
    async def after_write(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    _attach(mod, "handoff_scenario", handoff_scenario)
    _attach(mod, "triage", triage)
    _attach(mod, "specialist", specialist)
    _attach(mod, "after_write", after_write)

    result = discover_scenarios((mod.__name__,))

    assert dict(result.agent_handlers) == {"triage": triage, "specialist": specialist}
    assert dict(result.agent_routes) == {"triage": ("specialist",), "specialist": ()}
    assert dict(result.continuation_handlers) == {"after-write": after_write}


def test_discover_scenarios_rejects_duplicate_agent_id(fake_modules: list[str]) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_dup_agent_a")
    mod_b = _register_module(fake_modules, "discovery_test_dup_agent_b")

    @agent_handler("duplicate-agent")
    async def agent_one(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @agent_handler("duplicate-agent")
    async def agent_two(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    _attach(mod_a, "agent_one", agent_one)
    _attach(mod_b, "agent_two", agent_two)

    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert excinfo.value.code == "AGENT_HANDLER_DUPLICATE"
    assert excinfo.value.detail == "duplicate-agent"


def test_discover_scenarios_rejects_duplicate_continuation_name(
    fake_modules: list[str],
) -> None:
    mod_a = _register_module(fake_modules, "discovery_test_dup_continuation_a")
    mod_b = _register_module(fake_modules, "discovery_test_dup_continuation_b")

    @continuation_handler("duplicate-continuation")
    async def continuation_one(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    @continuation_handler("duplicate-continuation")
    async def continuation_two(context: ScenarioContext) -> dict[str, object]:
        return {"context": context}

    _attach(mod_a, "continuation_one", continuation_one)
    _attach(mod_b, "continuation_two", continuation_two)

    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios((mod_a.__name__, mod_b.__name__))

    assert excinfo.value.code == "CONTINUATION_HANDLER_DUPLICATE"
    assert excinfo.value.detail == "duplicate-continuation"


def test_discover_scenarios_rejects_route_to_undeclared_agent(
    fake_modules: list[str],
) -> None:
    mod = _register_module(fake_modules, "discovery_test_undeclared_target")

    @scenario(
        "handoff.orphan_scenario",
        max_model_calls=0,
        allowed_handoffs=("nobody",),
    )
    async def orphan_scenario(context: ScenarioContext) -> ScenarioResponse:
        return ScenarioResponse.handoff_to("nobody", input={}, reason="route to nobody")

    _attach(mod, "orphan_scenario", orphan_scenario)

    with pytest.raises(ScenarioDiscoveryError) as excinfo:
        discover_scenarios((mod.__name__,))

    assert excinfo.value.code == "HANDOFF_TARGET_NOT_FOUND"
    assert excinfo.value.detail == "nobody"
