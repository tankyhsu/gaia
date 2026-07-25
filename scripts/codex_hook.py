"""Codex lifecycle hooks for the Gaia change-set workflow."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import change_set

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.9 is still the macOS system default.
    from datetime import datetime, timezone

    UTC = timezone.utc  # noqa: UP017 - datetime.UTC does not exist on Python 3.9.

ROOT = Path(__file__).parents[1]
SESSION_DIR = change_set.git_dir() / "gaia" / "sessions"
AUDIT_PATH = Path(
    os.environ.get(
        "GAIA_HOOK_AUDIT_PATH",
        str(change_set.git_dir() / "gaia" / "hook-events.jsonl"),
    )
)
COMMIT_PATTERN = re.compile(r"(?:^|[;&|]\s*)(?:/usr/bin/)?git(?:\s+-C\s+\S+)?\s+commit\b")
STAGE_PATTERN = re.compile(r"(?:^|[;&|]\s*)(?:/usr/bin/)?git(?:\s+-C\s+\S+)?\s+add\b")

AGENT_CONTEXT = """
Gaia uses a repository-enforced change-set workflow. For any task
that edits Gaia tracked files:
run `make change-start INTENT="<observable outcome>" KIND=<kind>` before editing; keep code, tests,
documentation, generated contracts, and release impact synchronized; run `make agent-check` before
reporting completion; stage only intended files and run `make change-ready` before git commit.
Read AGENTS.md and CONTRIBUTING.md. Discussion and read-only review do not create a change set.
""".strip()


def _read_event() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise ValueError("hook input must be a JSON object")
    return value


def _write(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def _audit(
    name: str,
    outcome: str,
    event: dict[str, Any],
    *,
    detail: str | None = None,
) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": name,
        "session_id": str(event.get("session_id", "unknown")),
        "outcome": outcome,
    }
    source = event.get("source")
    if isinstance(source, str) and source:
        record["source"] = source
    tool_name = event.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        record["tool_name"] = tool_name
    if detail:
        record["detail"] = detail[:500]
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def _session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def _record_session_baseline(session_id: str, *, replace: bool = False) -> None:
    path = _session_path(session_id)
    if path.exists() and not replace:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"working_fingerprint": change_set.working_fingerprint()}, indent=2) + "\n",
        encoding="utf-8",
    )


def _session_changed(session_id: str) -> bool:
    path = _session_path(session_id)
    if not path.exists():
        _record_session_baseline(session_id)
        return False
    baseline = json.loads(path.read_text(encoding="utf-8"))
    return baseline.get("working_fingerprint") != change_set.working_fingerprint()


def _command(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return ""
    value = tool_input.get("command", tool_input.get("cmd", ""))
    return value if isinstance(value, str) else ""


def session_start(event: dict[str, Any]) -> int:
    _record_session_baseline(str(event.get("session_id", "unknown")))
    _audit("SessionStart", "context-injected", event)
    _write(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": AGENT_CONTEXT,
            }
        }
    )
    return 0


def user_prompt_submit(event: dict[str, Any]) -> int:
    _audit("UserPromptSubmit", "context-injected", event)
    _write(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": AGENT_CONTEXT,
            }
        }
    )
    return 0


def pre_tool_use(event: dict[str, Any]) -> int:
    command = _command(event)
    if not COMMIT_PATTERN.search(command):
        _audit("PreToolUse", "not-applicable", event)
        _write({})
        return 0
    staged_gaia = change_set.changed_paths(staged=True)
    commit_stages_files = STAGE_PATTERN.search(command) or re.search(
        r"\bgit(?:\s+-C\s+\S+)?\s+commit\s+[^;&|]*(?:-a|--all)\b",
        command,
    )
    if not staged_gaia and not commit_stages_files:
        _audit("PreToolUse", "not-applicable", event)
        _write({})
        return 0
    if "--no-verify" in command:
        reason = "Gaia policy forbids git commit --no-verify."
    else:
        completed = subprocess.run(
            (sys.executable, str(ROOT / "scripts/change_set.py"), "check-receipt"),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            _audit("PreToolUse", "allowed", event, detail="verification receipt is current")
            _write({})
            return 0
        reason = completed.stderr.strip() or completed.stdout.strip()
    _audit("PreToolUse", "denied", event, detail=reason)
    _write(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )
    return 0


def _stop(event: dict[str, Any]) -> int:
    session_id = str(event.get("session_id", "unknown"))
    if not _session_changed(session_id):
        _audit(str(event.get("hook_event_name", "Stop")), "unchanged", event)
        _write({"continue": True})
        return 0
    completed = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts/change_set.py"),
            "verify",
            "--run-checks",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        _record_session_baseline(session_id, replace=True)
        _audit(str(event.get("hook_event_name", "Stop")), "verified", event)
        _write({"continue": True})
        return 0
    output = (completed.stderr + "\n" + completed.stdout).strip()
    reason = (
        "Gaia Change Set verification failed. Resolve every item before finishing:\n"
        + output[-2200:]
    )
    if event.get("stop_hook_active"):
        _audit(
            str(event.get("hook_event_name", "Stop")),
            "reported-after-retry",
            event,
            detail=reason,
        )
        _write({"continue": True, "systemMessage": reason})
        return 0
    _audit(str(event.get("hook_event_name", "Stop")), "blocked", event, detail=reason)
    _write({"decision": "block", "reason": reason})
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: codex_hook.py EVENT", file=sys.stderr)
        return 2
    event: dict[str, Any] = {}
    name = sys.argv[1]
    try:
        event = _read_event()
        if name == "session-start":
            return session_start(event)
        if name == "user-prompt-submit":
            return user_prompt_submit(event)
        if name == "pre-tool-use":
            return pre_tool_use(event)
        if name == "stop":
            return _stop(event)
        if name == "subagent-stop":
            return _stop(event)
        print(f"unknown hook event: {name}", file=sys.stderr)
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        try:
            _audit(name, "error", event, detail=str(error))
        except OSError:
            pass
        print(f"GAIA_CODEX_HOOK_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
