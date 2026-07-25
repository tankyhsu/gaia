from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
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
hook_manager = _load_script("hook_manager")


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


def test_codex_hook_audit_does_not_store_prompt_or_command(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    audit_path = tmp_path / "hook-events.jsonl"
    monkeypatch.setattr(codex_hook, "AUDIT_PATH", audit_path)  # type: ignore[attr-defined]

    assert (
        codex_hook.pre_tool_use(
            {
                "session_id": "session-1",
                "tool_name": "functions.exec_command",
                "prompt": "private user request",
                "tool_input": {"cmd": "echo private-command"},
            }
        )
        == 0
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    text = audit_path.read_text(encoding="utf-8")
    event = json.loads(text)
    assert event["event"] == "PreToolUse"
    assert event["outcome"] == "not-applicable"
    assert event["session_id"] == "session-1"
    assert "private user request" not in text
    assert "private-command" not in text


def test_codex_hook_denies_commit_without_current_receipt(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    monkeypatch.setattr(codex_hook, "AUDIT_PATH", tmp_path / "events.jsonl")  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        codex_hook.change_set,
        "changed_paths",
        lambda *, staged: ("src/gaia/api/app.py",),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        codex_hook.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="No staged verification receipt.",
        ),
    )

    assert (
        codex_hook.pre_tool_use(
            {
                "session_id": "session-2",
                "hook_event_name": "PreToolUse",
                "tool_input": {"cmd": "git commit -m test"},
            }
        )
        == 0
    )
    response = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "No staged verification receipt" in output["permissionDecisionReason"]


def test_workspace_forwarding_config_targets_gaia_hook() -> None:
    config = hook_manager.codex_config(PROJECT_ROOT)

    session_command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    matcher = config["hooks"]["PreToolUse"][0]["matcher"]
    assert str(PROJECT_ROOT / "scripts" / "codex_hook.py") in session_command
    assert "functions\\.exec_command" in matcher
