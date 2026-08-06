"""Import-time discovery of decorated scenarios and tools.

`discover_scenarios` imports a fixed, explicit list of module paths and inventories the
`@scenario`, `@read_tool`, and `@write_tool` decorated functions each module defines at its
own top level. It performs no package walking and no module-name-prefix matching: only the
exact module names passed in are imported.

Scenario module purity contract
--------------------------------
Because `importlib.import_module` executes a module's top-level code, Scenario modules listed
under `scenarios.modules` MUST be import-pure. At import time a Scenario module may only:

- define functions and classes;
- define constants;
- attach decorator metadata (`@scenario`, `@read_tool`, `@write_tool`);
- import other pure modules.

A Scenario module MUST NOT, at import time: open network or database connections, resolve
secrets, read or write files, construct a client that needs explicit release, or start threads
or event loops. All such resources belong in Starter components registered with
`ComponentScope.APPLICATION` and released by the application lifespan (`AsyncExitStack`).
Breaking this contract means a resource escapes lifespan management and reappears as a
mysterious real connection whenever something merely imports the module — including static
commands such as `gaia check` that are not supposed to touch any external system.

Import failures are distinguished by cause, not just reported as "module not found":
`SCENARIO_MODULE_NOT_FOUND` means the declared module path itself (or one of its parent
packages) does not exist, so the fix is in `scenarios.modules`. `SCENARIO_MODULE_IMPORT_FAILED`
means the declared module exists and was found, but importing it failed for another reason —
a missing third-party dependency, a circular import, or a bad `from x import y` inside it — so
the fix is inside that module or its own dependencies, not in `scenarios.modules`.

This module does **not** enforce the contract above. `discover_scenarios` stays a plain,
side-effect-free import-and-inventory step (no AST parsing, no extra I/O of its own). A
separate static import-purity checker, `gaia.diagnostics.import_purity.scan_module_purity`,
flags obvious violations without importing the target module, and `gaia check` runs it
against every declared module before `configure()` imports them for real. That checker is a
best-effort lint (fixed allowlist, resolved-source matching only), not an isolation
guarantee — see its module docstring for exactly what it does and does not catch.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from gaia._authoring.scenario import (
    ScenarioHandler,
    ScenarioSpec,
    get_agent_handler_spec,
    get_continuation_handler_name,
    get_scenario_spec,
)
from gaia._authoring.tool import get_tool_spec
from gaia.contracts.models import ErrorCode
from gaia.spi.tool import ToolHandler

_SCENARIO_ATTR = "__gaia_scenario_spec__"
_TOOL_ATTR = "__gaia_tool_spec__"
_AGENT_HANDLER_ATTR = "__gaia_agent_handler__"
_CONTINUATION_HANDLER_ATTR = "__gaia_continuation_handler__"


@dataclass(frozen=True)
class DiscoveredScenarios:
    """Deterministic inventory of decorated scenarios and tools found in given modules."""

    scenarios: tuple[ScenarioSpec, ...]
    scenario_handlers: tuple[ScenarioHandler, ...]
    tool_handlers: tuple[ToolHandler, ...]
    agent_handlers: Mapping[str, ScenarioHandler]
    agent_routes: Mapping[str, tuple[str, ...]]
    continuation_handlers: Mapping[str, ScenarioHandler]


class ScenarioDiscoveryError(ValueError):
    """Raised when a declared module cannot be imported or declares a duplicate name."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}:{detail}")
        self.code = code
        self.detail = detail


def _classify_module_not_found(
    module_name: str, error: ModuleNotFoundError
) -> ScenarioDiscoveryError:
    """Tell "the declared module itself does not exist" apart from "it exists but one of
    its own imports is missing".

    `ModuleNotFoundError.name` names the specific module the import system could not find,
    which is not necessarily `module_name`. Importing `"myapp.flows"` raises with
    `error.name == "myapp.flows"` when that exact submodule is absent, but with
    `error.name == "myapp"` when the parent package itself is absent (Python resolves parent
    packages first) — both mean the declared module is not importable and should be reported
    as `SCENARIO_MODULE_NOT_FOUND`. Any other `error.name` (e.g. a third-party dependency the
    declared module tries to import at its own top level) means the declared module was found
    and started executing, so it is a `SCENARIO_MODULE_IMPORT_FAILED` — blaming
    `scenarios.modules` for that would send operators to fix the wrong file.
    """

    missing_name = error.name
    declared_module_missing = missing_name is not None and (
        missing_name == module_name or module_name.startswith(f"{missing_name}.")
    )
    if declared_module_missing:
        return ScenarioDiscoveryError("SCENARIO_MODULE_NOT_FOUND", module_name)
    detail = (
        f"{module_name}: no module named {missing_name!r}"
        if missing_name is not None
        else f"{module_name}: {error}"
    )
    return ScenarioDiscoveryError("SCENARIO_MODULE_IMPORT_FAILED", detail)


def discover_scenarios(modules: tuple[str, ...]) -> DiscoveredScenarios:
    """Import `modules` in order and collect the decorated members each one defines.

    Only members whose `__module__` equals the imported module's `__name__` are collected, so
    a scenario or tool function that is merely imported into a second module (re-exported, or
    imported for reuse) is not registered a second time. Results are sorted by `scenario_id`,
    tool name, agent id, and continuation name so the returned collections are deterministic
    regardless of `vars()` ordering or which module in `modules` happened to define a given
    name.

    Beyond duplicate names, this also validates that every handoff route -- whether declared
    on `@scenario(allowed_handoffs=...)` or on an `@agent_handler(allowed_handoffs=...)` --
    names a target agent that some `@agent_handler` in the discovered modules actually
    declares. The routing table has no implicit default edges, so an undeclared target can
    never become reachable at runtime; catching that here means the failure surfaces at
    startup (`HANDOFF_TARGET_NOT_FOUND`) instead of during a live run.
    """

    scenario_specs: dict[str, ScenarioSpec] = {}
    scenario_handlers_by_id: dict[str, ScenarioHandler] = {}
    tool_handlers_by_name: dict[str, ToolHandler] = {}
    agent_handlers_by_id: dict[str, ScenarioHandler] = {}
    agent_routes_by_id: dict[str, tuple[str, ...]] = {}
    continuation_handlers_by_name: dict[str, ScenarioHandler] = {}

    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            raise _classify_module_not_found(module_name, error) from error
        except ImportError as error:
            raise ScenarioDiscoveryError(
                "SCENARIO_MODULE_IMPORT_FAILED", f"{module_name}: {error}"
            ) from error

        for obj in vars(module).values():
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            if hasattr(obj, _SCENARIO_ATTR):
                spec = get_scenario_spec(obj)
                if spec.scenario_id in scenario_specs:
                    raise ScenarioDiscoveryError("SCENARIO_DUPLICATE", spec.scenario_id)
                scenario_specs[spec.scenario_id] = spec
                scenario_handlers_by_id[spec.scenario_id] = obj
            if hasattr(obj, _TOOL_ATTR):
                tool_name = get_tool_spec(obj).definition.name
                if tool_name in tool_handlers_by_name:
                    raise ScenarioDiscoveryError("SCENARIO_TOOL_DUPLICATE", tool_name)
                tool_handlers_by_name[tool_name] = obj
            if hasattr(obj, _AGENT_HANDLER_ATTR):
                agent_spec = get_agent_handler_spec(obj)
                if agent_spec.agent_id in agent_handlers_by_id:
                    raise ScenarioDiscoveryError("AGENT_HANDLER_DUPLICATE", agent_spec.agent_id)
                agent_handlers_by_id[agent_spec.agent_id] = obj
                agent_routes_by_id[agent_spec.agent_id] = agent_spec.allowed_handoffs
            if hasattr(obj, _CONTINUATION_HANDLER_ATTR):
                continuation_name = get_continuation_handler_name(obj)
                if continuation_name in continuation_handlers_by_name:
                    raise ScenarioDiscoveryError(
                        "CONTINUATION_HANDLER_DUPLICATE", continuation_name
                    )
                continuation_handlers_by_name[continuation_name] = obj

    unknown_targets: set[str] = set()
    for spec in scenario_specs.values():
        unknown_targets.update(
            target for target in spec.allowed_handoffs if target not in agent_handlers_by_id
        )
    for targets in agent_routes_by_id.values():
        unknown_targets.update(
            target for target in targets if target not in agent_handlers_by_id
        )
    if unknown_targets:
        raise ScenarioDiscoveryError(
            ErrorCode.HANDOFF_TARGET_NOT_FOUND.value, ", ".join(sorted(unknown_targets))
        )

    sorted_scenario_ids = sorted(scenario_specs)
    sorted_tool_names = sorted(tool_handlers_by_name)
    sorted_agent_ids = sorted(agent_handlers_by_id)
    sorted_continuation_names = sorted(continuation_handlers_by_name)

    return DiscoveredScenarios(
        scenarios=tuple(scenario_specs[sid] for sid in sorted_scenario_ids),
        scenario_handlers=tuple(scenario_handlers_by_id[sid] for sid in sorted_scenario_ids),
        tool_handlers=tuple(tool_handlers_by_name[name] for name in sorted_tool_names),
        agent_handlers=MappingProxyType(
            {aid: agent_handlers_by_id[aid] for aid in sorted_agent_ids}
        ),
        agent_routes=MappingProxyType(
            {aid: agent_routes_by_id[aid] for aid in sorted_agent_ids}
        ),
        continuation_handlers=MappingProxyType(
            {name: continuation_handlers_by_name[name] for name in sorted_continuation_names}
        ),
    )
