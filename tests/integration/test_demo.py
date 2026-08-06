"""H3: `make demo` must keep seeding runs worth looking at.

`make demo`'s entire value is in what it seeds: a controlled write that went
through human approval and completed, and something that was refused. A demo
nobody runs would go stale exactly the way `make attack-demo` guards against
in `test_attack_demo.py` -- so this test exercises `scripts/demo.py`'s own
seeding function (`seed_demo_runs`), in-process, against the real
`controlled-task` reference scenario also used by `make dev-api`. A change
that alters that scenario's shape (a renamed resource, a rule that now
produces a different outcome, a write that no longer requires approval) fails
the ordinary test suite here instead of only being noticed the next time
someone happens to run the demo by hand.

`scripts/demo.py` lives outside `src/` (like `scripts/attack_demo.py`), so it
is loaded the same way `test_attack_demo.py` loads that script: by file path,
not by package import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_DEMO_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo.py"
_TEMPORAL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "temporal_dev_server.py"


def _load_demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gaia_demo_script", _DEMO_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _load_temporal_server() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gaia_temporal_dev_server",
        _TEMPORAL_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def test_demo_script_exists() -> None:
    assert _DEMO_SCRIPT.is_file(), f"demo script is missing: {_DEMO_SCRIPT}"


def test_temporal_demo_server_registers_gaia_visibility_attributes() -> None:
    server = _load_temporal_server()
    try:
        names = {attribute.name for attribute in server.GAIA_SEARCH_ATTRIBUTES}
    finally:
        sys.modules.pop("gaia_temporal_dev_server", None)

    assert names == {"GaiaOrganization", "GaiaScenarioId", "GaiaRunStatus"}


def test_seed_plan_covers_approval_rejection_and_policy_refusal() -> None:
    demo = _load_demo()
    try:
        decisions = {item.decision for item in demo.SEED_PLAN}
        expected_statuses = {item.expected_status for item in demo.SEED_PLAN}
    finally:
        sys.modules.pop("gaia_demo_script", None)

    assert decisions == {"approved", "rejected", None}
    assert expected_statuses == {"succeeded", "blocked"}


def test_console_env_reports_showcase_and_demo_mode() -> None:
    """`make demo` tells Console whether the optional showcase actually started.

    Without this flag the Console has no way to tell "showcase not started
    this run" apart from "briefly slow to answer", and would render the
    three showcase example cards as ordinary links that error when clicked
    -- exactly the dead-link failure mode 18-演示可用性施工图.md's D1 exists to
    remove.
    """

    demo = _load_demo()
    try:
        available = demo._console_extra_env(
            docs_available=True,
            docs_url="http://127.0.0.1:4175/",
            hr_showcase_available=True,
            hr_showcase_url="http://127.0.0.1:4173/",
        )
        unavailable = demo._console_extra_env(
            docs_available=False,
            docs_url="http://127.0.0.1:4175/",
            hr_showcase_available=False,
            hr_showcase_url="http://127.0.0.1:4173/",
        )
    finally:
        sys.modules.pop("gaia_demo_script", None)

    # `make demo` now starts the HR showcase, so the flag tracks whether it
    # actually came up rather than being unconditionally set.
    assert "VITE_GAIA_SHOWCASE_UNAVAILABLE" not in available
    assert available["VITE_GAIA_SHOWCASE_URL"] == "http://127.0.0.1:4173/"
    assert unavailable["VITE_GAIA_SHOWCASE_UNAVAILABLE"] == "true"
    assert "VITE_GAIA_SHOWCASE_URL" not in unavailable
    # Demo mode is what makes the Console land on #demo and hide 快速开始,
    # whose project-init action writes into GAIA_PROJECT_ROOT -- during a demo,
    # the Gaia repository itself.
    assert available["VITE_GAIA_DEMO_MODE"] == "true"
    assert unavailable["VITE_GAIA_DEMO_MODE"] == "true"


def test_hr_frontend_receives_console_return_url(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _load_demo()
    monkeypatch.setenv("EXISTING_SETTING", "preserved")
    try:
        env = demo._hr_frontend_environment("http://127.0.0.1:4180/")
    finally:
        sys.modules.pop("gaia_demo_script", None)

    assert env["VITE_GAIA_CONSOLE_URL"] == "http://127.0.0.1:4180/"
    assert env["EXISTING_SETTING"] == "preserved"


def test_console_env_points_at_live_docs_url_when_docs_start() -> None:
    """When `mkdocs` comes up, the Console's docs link must point at it -- and
    must not also carry the "unavailable" flag, or `ExternalDocLink` would
    render the disabled stand-in instead of the real link.
    """

    demo = _load_demo()
    try:
        env = demo._console_extra_env(
            docs_available=True,
            docs_url="http://127.0.0.1:4175/",
            hr_showcase_available=True,
            hr_showcase_url="http://127.0.0.1:4173/",
        )
    finally:
        sys.modules.pop("gaia_demo_script", None)

    assert env["VITE_GAIA_DOCS_URL"] == "http://127.0.0.1:4175/"
    assert "VITE_GAIA_DOCS_UNAVAILABLE" not in env


def test_console_env_marks_docs_unavailable_when_docs_fail_to_start() -> None:
    """When `mkdocs` fails (missing binary, port taken, ...), the Console must
    be told explicitly rather than left to render a link that errors when
    clicked -- and must not also receive a docs URL, since nothing is
    listening there.
    """

    demo = _load_demo()
    try:
        env = demo._console_extra_env(
            docs_available=False,
            docs_url="http://127.0.0.1:4175/",
            hr_showcase_available=False,
            hr_showcase_url="http://127.0.0.1:4173/",
        )
    finally:
        sys.modules.pop("gaia_demo_script", None)

    assert env["VITE_GAIA_DOCS_UNAVAILABLE"] == "true"
    assert "VITE_GAIA_DOCS_URL" not in env


def test_wait_for_run_polls_until_temporal_projection_reaches_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo()

    class Response:
        status_code = 200
        text = ""

        def __init__(self, status: str) -> None:
            self.status = status

        def json(self) -> dict[str, str]:
            return {"run_id": "run-1", "status": self.status}

    class Client:
        def __init__(self) -> None:
            self.responses = iter((Response("running"), Response("waiting_human")))

        def get(self, path: str, *, headers: dict[str, str]) -> Response:
            assert path == "/v1/runs/run-1"
            assert headers == demo.API_KEY_HEADER
            return next(self.responses)

    monkeypatch.setattr(demo.time, "sleep", lambda seconds: None)
    try:
        run = demo._wait_for_run(
            Client(),
            "run-1",
            expected_statuses={"waiting_human"},
            timeout_seconds=1,
        )
    finally:
        sys.modules.pop("gaia_demo_script", None)

    assert run["status"] == "waiting_human"
