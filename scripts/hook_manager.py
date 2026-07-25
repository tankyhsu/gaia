"""Install and inspect Gaia's Codex and Git workflow hooks."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1].resolve()
AUDIT_PATH = ROOT / ".git" / "gaia" / "hook-events.jsonl"


def codex_config(repo_root: Path) -> dict[str, Any]:
    script = repo_root / "scripts" / "codex_hook.py"
    command = f'python3 "{script}"'
    return {
        "description": "Gaia workspace hook forwarding; managed by scripts/hook_manager.py",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} session-start",
                            "timeout": 10,
                            "statusMessage": "Loading Gaia development contract",
                        }
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} user-prompt-submit",
                            "timeout": 10,
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash|functions\\.exec_command|functions\\.exec",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} pre-tool-use",
                            "timeout": 30,
                            "statusMessage": "Checking Gaia commit readiness",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} stop",
                            "timeout": 600,
                            "statusMessage": "Verifying Gaia change set",
                        }
                    ]
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} subagent-stop",
                            "timeout": 600,
                            "statusMessage": "Verifying delegated Gaia change",
                        }
                    ]
                }
            ],
        },
    }


def install(workspace_root: Path) -> None:
    workspace_root = workspace_root.resolve()
    config_path = workspace_root / ".codex" / "hooks.json"
    if config_path.exists():
        current = json.loads(config_path.read_text(encoding="utf-8"))
        description = current.get("description") if isinstance(current, dict) else None
        if not isinstance(description, str) or "Gaia" not in description:
            raise ValueError(
                f"{config_path} already exists and is not managed by Gaia; merge it manually"
            )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(codex_config(ROOT), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "config", "core.hooksPath", ".githooks"),
        cwd=ROOT,
        check=True,
    )
    print(f"Codex hooks: {config_path}")
    print("Git hooks: .githooks")


def read_audit(limit: int) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    rows = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        value = json.loads(row)
        if isinstance(value, dict):
            events.append(value)
    return events


def status(workspace_root: Path, limit: int) -> int:
    config_path = workspace_root.resolve() / ".codex" / "hooks.json"
    configured_path = subprocess.run(
        ("git", "config", "--get", "core.hooksPath"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    feature_output = subprocess.run(
        ("codex", "features", "list"),
        check=False,
        capture_output=True,
        text=True,
    )
    hooks_feature = next(
        (
            line
            for line in feature_output.stdout.splitlines()
            if line.split(maxsplit=1)[0:1] == ["hooks"]
        ),
        "",
    )
    feature_ready = hooks_feature.rstrip().endswith("true")
    codex_ready = config_path.exists()
    git_ready = configured_path == ".githooks"
    print(
        f"Codex hooks feature: {'enabled' if feature_ready else 'disabled or unavailable'}"
    )
    print(f"Codex discovery config: {'present' if codex_ready else 'missing'} ({config_path})")
    print("Codex hook trust: confirm in Codex after any hooks.json content change")
    print(f"Git hooks path: {'ready' if git_ready else 'missing'} ({configured_path or 'unset'})")
    events = read_audit(limit)
    print(f"Recent audited events: {len(events)}")
    for event in events:
        print(
            f"- {event.get('timestamp')} {event.get('event')} "
            f"{event.get('outcome')} session={event.get('session_id')}"
        )
    return 0 if feature_ready and codex_ready and git_ready else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--workspace-root", type=Path, default=ROOT)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--workspace-root", type=Path, default=ROOT)
    status_parser.add_argument("--limit", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "install":
            install(args.workspace_root)
            return 0
        return status(args.workspace_root, args.limit)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"GAIA_HOOK_MANAGER_ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
