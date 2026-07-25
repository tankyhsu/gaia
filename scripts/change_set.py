"""Change-set impact analysis and verification for Gaia development."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
REPO_ROOT = Path(
    subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
)
PROJECT_RELATIVE = ROOT.relative_to(REPO_ROOT).as_posix()
PROJECT_PREFIX = "" if PROJECT_RELATIVE == "." else f"{PROJECT_RELATIVE}/"
MANAGED_ROOT_PATHS = (
    ".codex/hooks.json",
    ".github/PULL_REQUEST_TEMPLATE/gaia.md",
    ".github/workflows/gaia-ci.yml",
    ".github/workflows/gaia-nightly.yml",
    ".github/workflows/gaia-release.yml",
)
WORK_DIR = ROOT / ".gaia-work"
MANIFEST_PATH = WORK_DIR / "change-set.json"
KINDS = ("feature", "bugfix", "refactor", "docs", "test", "build")
EXEMPT_AREAS = ("tests", "docs", "release")


@dataclass(frozen=True)
class Impact:
    paths: tuple[str, ...]
    python: bool
    web: bool
    docs: bool
    contracts: bool
    tests_required: bool
    docs_required: bool
    release_required: bool
    tests_changed: bool
    docs_changed: bool
    release_changed: bool


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_repo(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _managed_path(path: str) -> str | None:
    if not PROJECT_PREFIX:
        return path
    if path.startswith(PROJECT_PREFIX):
        return path.removeprefix(PROJECT_PREFIX)
    if path in MANAGED_ROOT_PATHS:
        return path
    return None


def _split_paths(output: str) -> tuple[str, ...]:
    return tuple(path for path in output.split("\0") if path)


def changed_paths(*, staged: bool) -> tuple[str, ...]:
    pathspecs = (PROJECT_PREFIX.rstrip("/") or ".", *MANAGED_ROOT_PATHS)
    if staged:
        output = _git_repo(
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            "--",
            *pathspecs,
        ).stdout
        return tuple(
            sorted(
                managed
                for path in _split_paths(output)
                if (managed := _managed_path(path)) is not None
            )
        )

    tracked = _split_paths(
        _git_repo(
            "diff",
            "HEAD",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            "--",
            *pathspecs,
        ).stdout
    )
    untracked = _split_paths(
        _git_repo(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *pathspecs,
        ).stdout
    )
    return tuple(
        sorted(
            {
                managed
                for path in (*tracked, *untracked)
                if (managed := _managed_path(path)) is not None
            }
        )
    )


def staged_paths_outside_change_set() -> tuple[str, ...]:
    output = _git_repo(
        "diff",
        "--cached",
        "--name-only",
        "-z",
        "--diff-filter=ACDMRTUXB",
    ).stdout
    return tuple(sorted(path for path in _split_paths(output) if _managed_path(path) is None))


def working_fingerprint() -> str:
    digest = hashlib.sha256()
    pathspecs = (PROJECT_PREFIX.rstrip("/") or ".", *MANAGED_ROOT_PATHS)
    digest.update(
        _git_repo("diff", "--binary", "HEAD", "--", *pathspecs).stdout.encode()
    )
    untracked = _split_paths(
        _git_repo(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *pathspecs,
        ).stdout
    )
    for relative in untracked:
        path = REPO_ROOT / relative
        digest.update(relative.encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def classify_paths(paths: tuple[str, ...]) -> Impact:
    def starts(prefixes: tuple[str, ...]) -> bool:
        return any(path.startswith(prefixes) for path in paths)

    python = starts(("src/", "tests/", "scripts/")) or any(
        path in {"pyproject.toml", "alembic.ini"} for path in paths
    )
    web = starts(("apps/web/src/", "apps/web/tests/")) or any(
        path in {"apps/web/package.json", "apps/web/package-lock.json"} for path in paths
    )
    docs_changed = starts(("developer-docs/", "docs/")) or any(
        path in {"README.md", "QUICKSTART.md", "CONTRIBUTING.md", "CHANGELOG.md", "mkdocs.yml"}
        for path in paths
    )
    tests_changed = starts(("tests/", "apps/web/tests/"))
    release_changed = "CHANGELOG.md" in paths

    production_python = starts(("src/", "scripts/"))
    production_web = starts(("apps/web/src/",))
    pipeline = starts((".codex/", ".github/")) or any(
        path in {"AGENTS.md", "Makefile", "CONTRIBUTING.md"} for path in paths
    )
    public_python = starts(
        (
            "src/gaia/api/",
            "src/gaia/cli/",
            "src/gaia/config/",
            "src/gaia/contracts/",
            "src/gaia/guardrails/",
            "src/gaia/integrations/",
            "src/gaia/model_gateway/",
            "src/gaia/rag/",
            "src/gaia/runtime/",
            "src/gaia/sdk/",
            "src/gaia/starters/",
            "src/gaia/templates/",
        )
    )

    return Impact(
        paths=paths,
        python=python,
        web=web,
        docs=docs_changed or public_python or production_web or pipeline,
        contracts=starts(("src/gaia/api/", "src/gaia/contracts/")),
        tests_required=production_python or production_web,
        docs_required=public_python or production_web or pipeline,
        release_required=public_python or production_web,
        tests_changed=tests_changed,
        docs_changed=docs_changed,
        release_changed=release_changed,
    )


def load_manifest() -> dict[str, Any] | None:
    if not MANIFEST_PATH.exists():
        return None
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("change-set manifest must be a JSON object")
    return value


def save_manifest(manifest: dict[str, Any]) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def start_change(intent: str, kind: str) -> None:
    save_manifest(
        {
            "intent": intent.strip(),
            "kind": kind,
            "base_head": _git("rev-parse", "HEAD").stdout.strip(),
            "exemptions": {},
        }
    )
    print(f"Change set started: {kind} - {intent.strip()}")


def add_exemption(area: str, reason: str) -> None:
    manifest = load_manifest()
    if manifest is None:
        raise ValueError("no active change set; run make change-start first")
    exemptions = manifest.setdefault("exemptions", {})
    if not isinstance(exemptions, dict):
        raise ValueError("change-set exemptions must be an object")
    exemptions[area] = reason.strip()
    save_manifest(manifest)
    print(f"Recorded {area} exemption: {reason.strip()}")


def _valid_exemption(manifest: dict[str, Any], area: str) -> bool:
    exemptions = manifest.get("exemptions", {})
    if not isinstance(exemptions, dict):
        return False
    reason = exemptions.get(area)
    return isinstance(reason, str) and len(reason.strip()) >= 12


def validate_change(impact: Impact, manifest: dict[str, Any] | None) -> list[str]:
    if not impact.paths:
        return []
    errors: list[str] = []
    if manifest is None:
        return ["No active change set. Run make change-start before editing tracked files."]
    if not str(manifest.get("intent", "")).strip():
        errors.append("Change set intent is missing.")
    if manifest.get("kind") not in KINDS:
        errors.append(f"Change set kind must be one of: {', '.join(KINDS)}.")
    if impact.tests_required and not impact.tests_changed and not _valid_exemption(
        manifest, "tests"
    ):
        errors.append(
            "Production code changed without test changes or a justified tests exemption."
        )
    if impact.docs_required and not impact.docs_changed and not _valid_exemption(manifest, "docs"):
        errors.append("Public or pipeline behavior changed without documentation changes.")
    if (
        impact.release_required
        and not impact.release_changed
        and not _valid_exemption(manifest, "release")
    ):
        errors.append("User-visible code changed without CHANGELOG.md or a release exemption.")
    return errors


def _run(name: str, command: tuple[str, ...]) -> str | None:
    print(f"[change-set] {name}")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode == 0:
        return None
    return f"{name} failed with exit code {completed.returncode}."


def run_checks(impact: Impact) -> list[str]:
    errors: list[str] = []
    if impact.python:
        for name, command in (
            ("ruff", ("uv", "run", "ruff", "check", ".")),
            ("mypy", ("uv", "run", "mypy", "src")),
            (
                "pytest",
                (
                    "uv",
                    "run",
                    "pytest",
                    "-q",
                    "-m",
                    "not postgres and not redis and not external",
                ),
            ),
        ):
            if error := _run(name, command):
                errors.append(error)
    if impact.web:
        for name, command in (
            ("web build", ("npm", "--prefix", "apps/web", "run", "build")),
            ("web e2e", ("npm", "--prefix", "apps/web", "run", "test:e2e")),
        ):
            if error := _run(name, command):
                errors.append(error)
    if impact.docs:
        if error := _run("documentation", ("uv", "run", "mkdocs", "build", "--strict")):
            errors.append(error)
    if impact.contracts:
        if error := _run(
            "OpenAPI drift",
            ("uv", "run", "python", "scripts/check_openapi.py"),
        ):
            errors.append(error)
    return errors


def git_dir() -> Path:
    value = _git("rev-parse", "--git-dir").stdout.strip()
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def write_receipt(impact: Impact) -> Path:
    receipt_dir = git_dir() / "gaia"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / "change-verification.json"
    receipt_path.write_text(
        json.dumps(
            {
                "head": _git("rev-parse", "HEAD").stdout.strip(),
                "staged_tree": _git("write-tree").stdout.strip(),
                "impact": asdict(impact),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt_path


def check_receipt() -> list[str]:
    receipt_path = git_dir() / "gaia" / "change-verification.json"
    if not receipt_path.exists():
        return ["No staged verification receipt. Run make change-ready before git commit."]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    current_head = _git("rev-parse", "HEAD").stdout.strip()
    current_tree = _git("write-tree").stdout.strip()
    errors: list[str] = []
    if receipt.get("head") != current_head:
        errors.append("Verification receipt belongs to a different HEAD.")
    if receipt.get("staged_tree") != current_tree:
        errors.append("Staged files changed after verification. Run make change-ready again.")
    return errors


def print_status(impact: Impact, manifest: dict[str, Any] | None) -> None:
    print(
        json.dumps(
            {"manifest": manifest, "impact": asdict(impact)},
            ensure_ascii=False,
            indent=2,
        )
    )


def verify(*, staged: bool, checks: bool, receipt: bool) -> int:
    impact = classify_paths(changed_paths(staged=staged))
    manifest = load_manifest()
    print_status(impact, manifest)
    errors = validate_change(impact, manifest)
    if staged and (outside := staged_paths_outside_change_set()):
        errors.append(
            "Staged files outside the Gaia change set: " + ", ".join(outside)
        )
    if not errors and checks:
        errors.extend(run_checks(impact))
    if errors:
        print("\nChange set is not ready:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if receipt:
        if not staged:
            print("--write-receipt requires --staged", file=sys.stderr)
            return 2
        path = write_receipt(impact)
        print(f"Verification receipt: {path}")
    print("Change set verified.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--intent", required=True)
    start.add_argument("--kind", choices=KINDS, default="feature")

    exempt = subparsers.add_parser("exempt")
    exempt.add_argument("area", choices=EXEMPT_AREAS)
    exempt.add_argument("--reason", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--staged", action="store_true")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--staged", action="store_true")
    verify_parser.add_argument("--run-checks", action="store_true")
    verify_parser.add_argument("--write-receipt", action="store_true")

    subparsers.add_parser("check-receipt")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "start":
            start_change(args.intent, args.kind)
            return 0
        if args.command == "exempt":
            add_exemption(args.area, args.reason)
            return 0
        if args.command == "status":
            print_status(classify_paths(changed_paths(staged=args.staged)), load_manifest())
            return 0
        if args.command == "verify":
            return verify(
                staged=args.staged,
                checks=args.run_checks,
                receipt=args.write_receipt,
            )
        errors = check_receipt()
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("Staged verification receipt is current.")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"CHANGE_SET_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
