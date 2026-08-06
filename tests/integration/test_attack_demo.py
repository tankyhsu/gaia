"""The attack-and-defence demonstration must keep passing in CI.

`make attack-demo` exists to show that seven named controls cannot be bypassed.
That claim is only as durable as its enforcement: a demonstration nobody runs
degrades into a story about how the code used to behave. Running it here means
a change that breaks any of those defences fails the ordinary test suite,
rather than being discovered the next time someone happens to run the demo by
hand.

The script exits non-zero when any defence fails, so asserting on the exit code
is the whole contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DEMO = Path(__file__).resolve().parents[2] / "scripts" / "attack_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("gaia_attack_demo", _DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def test_attack_demo_script_exists() -> None:
    assert _DEMO.is_file(), f"attack demo script is missing: {_DEMO}"


def test_every_documented_defense_still_holds(capsys: pytest.CaptureFixture[str]) -> None:
    """Exit code 0 means all seven defences held; 1 means at least one did not."""

    module = _load_demo()
    try:
        exit_code = module.main()
    finally:
        sys.modules.pop("gaia_attack_demo", None)

    captured = capsys.readouterr()
    assert exit_code == 0, (
        "an attack that should have been refused was not; see the demo output:\n"
        f"{captured.out}"
    )
    assert "ALL DEFENSES HELD" in captured.out
    assert "*** DEFENSE FAILED ***" not in captured.out


def test_demo_reports_every_attack_it_promises() -> None:
    """Guard against an attack silently disappearing from the run.

    A defence that stops being exercised is indistinguishable, from the exit
    code alone, from one that still passes.
    """

    source = _DEMO.read_text(encoding="utf-8")
    for attack in (
        "Forged approver role",
        "Cross-organization access",
        "alg=none token",
        "RS256/HS256 key confusion",
        "Loosening a policy from config",
        "Denied tool called directly",
        "Import-time side effect",
    ):
        assert attack in source, f"attack no longer present in the demonstration: {attack}"
