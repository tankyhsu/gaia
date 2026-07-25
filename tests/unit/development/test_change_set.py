from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).parents[3]


def _load_script(name: str) -> ModuleType:
    path = PROJECT_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


change_set = _load_script("change_set")
codex_hook = _load_script("codex_hook")


def test_public_runtime_change_requires_tests_docs_and_release_note() -> None:
    impact = change_set.classify_paths(("src/gaia/api/app.py",))

    assert impact.tests_required is True
    assert impact.docs_required is True
    assert impact.release_required is True
    assert change_set.validate_change(
        impact,
        {
            "intent": "Expose a public API behavior",
            "kind": "feature",
            "exemptions": {},
        },
    ) == [
        "Production code changed without test changes or a justified tests exemption.",
        "Public or pipeline behavior changed without documentation changes.",
        "User-visible code changed without CHANGELOG.md or a release exemption.",
    ]


def test_complete_public_change_satisfies_impact_policy() -> None:
    impact = change_set.classify_paths(
        (
            "src/gaia/api/app.py",
            "tests/contract/test_api.py",
            "developer-docs/http-api.md",
            "CHANGELOG.md",
        )
    )

    assert change_set.validate_change(
        impact,
        {
            "intent": "Expose a public API behavior",
            "kind": "feature",
            "exemptions": {},
        },
    ) == []


def test_internal_change_can_record_concrete_exemptions() -> None:
    impact = change_set.classify_paths(("scripts/internal_refactor.py",))

    assert change_set.validate_change(
        impact,
        {
            "intent": "Refactor internal developer automation",
            "kind": "refactor",
            "exemptions": {
                "tests": "Covered by the existing script contract tests",
            },
        },
    ) == []


def test_pipeline_change_requires_documentation_but_not_release_note() -> None:
    impact = change_set.classify_paths((".codex/hooks.json",))

    assert impact.docs_required is True
    assert impact.release_required is False


def test_root_workflow_paths_are_managed_as_part_of_gaia() -> None:
    assert change_set._managed_path("src/gaia/api/app.py") == "src/gaia/api/app.py"
    assert change_set._managed_path(".github/workflows/gaia-ci.yml") == (
        ".github/workflows/gaia-ci.yml"
    )


def test_codex_hook_detects_commit_commands() -> None:
    pattern = codex_hook.COMMIT_PATTERN

    assert pattern.search("git commit -m 'verified'")
    assert pattern.search("git -C /tmp/project commit -m test")
    assert pattern.search("uv run pytest && git commit -m test")
    assert not pattern.search("git status")
    assert not pattern.search("echo git commit")


def test_codex_hook_detects_compound_stage_and_commit() -> None:
    assert codex_hook.STAGE_PATTERN.search("git add src && git commit -m test")
