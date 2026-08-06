"""`make demo`: one command from a fresh clone to real evidence in the Console.

Before this script existed, seeing anything working required starting the
API, discovering the local database was behind, migrating it, `curl`-ing a
run into existence, `curl`-ing an approval, starting the Console, and pasting
a UUID copied out of a terminal. That is an operating manual, not a
demonstration.

This script:
  1. Prepares a *disposable* SQLite database under ``var/gaia-demo.db`` --
     never ``var/gaia.db``, so running the demo can never disturb a
     developer's local state, and always starts from a blank file so it can
     never inherit the stale-schema problem that produced the
     ``no such column: runs.pending_result_json`` error this script replaces.
  2. Migrates that database with Alembic (the same migration chain
     production uses -- not a schema shortcut).
  3. Starts a disposable Temporal development server and the
     ``controlled-task`` application's real Worker.
  4. Starts the ``controlled-task`` reference API against that database.
  5. Seeds a handful of runs worth looking at: a controlled write that went
     through human approval and completed, one a human approver refused, and
     one refused by policy before a human was ever involved.
  6. Starts the Console, pointed at the demo API.
  7. Prints exactly one URL and one sentence, then waits for Ctrl+C to stop
     every demo process and exit -- leaving no process behind.

Every step above is a step a first-time reader could get wrong by hand; this
script is that operating manual, executed instead of read.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

import httpx

ROOT = Path(__file__).resolve().parents[1]
# Editable installs normally put `src/` on `sys.path` already; this is cheap
# insurance for the one import below (Alembic's `env.py` imports `gaia.
# persistence.models` in-process) in case this script is ever invoked outside
# of `uv run`.
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DEMO_DB_PATH = ROOT / "var" / "gaia-demo.db"
DEMO_DATABASE_URL = f"sqlite+aiosqlite:///{DEMO_DB_PATH}"
DEMO_TEMPORAL_DB_PATH = ROOT / "var" / "gaia-demo-temporal.db"

DEMO_TEMPORAL_HOST = "127.0.0.1"
DEMO_TEMPORAL_PORT = 7233
DEMO_API_HOST = "127.0.0.1"
DEMO_API_PORT = 8010
DEMO_CONSOLE_HOST = "127.0.0.1"
DEMO_CONSOLE_PORT = 4180

# Same host/port `make dev-docs` already serves on. The Console's own default
# for its documentation link (`apps/web/src/Console.tsx`) is
# `${location.hostname}:4175`, so starting docs here is what makes that
# existing default true during a demo instead of a dead link -- no Console
# constant needs to change for the success path.
DEMO_DOCS_HOST = "127.0.0.1"
DEMO_DOCS_PORT = 4175

# Deliberately distinct from the developer-facing `make dev-api` (8000) /
# `make dev-console` (4173) ports so `make demo` can run alongside them
# without colliding -- it must never require stopping a developer's own
# servers to be tried. Docs share `make dev-docs`'s port (4175) on purpose:
# docs are read-only and idempotent to serve twice is not a concern here
# because `make demo` and `make dev-docs` binding the same port at the same
# time simply means one of them fails to start docs, which is handled below
# as a non-fatal "docs unavailable" outcome, not a crashed demo.
DEMO_API_KEY = os.environ.get("GAIA_API_KEY", "gaia-dev-key")
API_KEY_HEADER = {"X-Gaia-Api-Key": DEMO_API_KEY}

# The HR reference application (`docs/施工图/18-演示可用性施工图.md` D5) lives in a
# sibling repository, not inside this one, because it is a standalone example
# of building *on* Gaia rather than a part of Gaia itself. Its path is
# overridable so a checkout in a different location (or a CI job that clones
# it somewhere else) does not require editing this script.
DEMO_HR_SHOWCASE_ROOT = Path(
    os.environ.get(
        "GAIA_HR_SHOWCASE_PATH", str(ROOT.parent / "showcase" / "gaia-hr-suite")
    )
)
DEMO_HR_BACKEND_ROOT = DEMO_HR_SHOWCASE_ROOT / "backend"
DEMO_HR_FRONTEND_ROOT = DEMO_HR_SHOWCASE_ROOT / "frontend"
DEMO_HR_PYTHON = DEMO_HR_BACKEND_ROOT / ".venv" / "bin" / "python"
DEMO_HR_GAIA_BIN = DEMO_HR_BACKEND_ROOT / ".venv" / "bin" / "gaia"

DEMO_HR_API_HOST = "127.0.0.1"
DEMO_HR_API_PORT = 8001
# The showcase's own `frontend/vite.config.ts` already pins this port -- it is
# not passed on the command line so there is exactly one place that decides
# it. It is free during `make demo` because the Console itself runs on 4180,
# not the developer-facing 4173 `make dev-console` uses; see
# `apps/web/vite.config.ts` and this module's docstring.
DEMO_HR_FRONTEND_HOST = "127.0.0.1"
DEMO_HR_FRONTEND_PORT = 4173


class DemoError(RuntimeError):
    """A failure with a concrete next step, never a bare traceback.

    Mirrors the operator-guidance shape already established for
    `SCENARIO_MODULE_NOT_FOUND` (see `gaia.diagnostics.error_catalog` and
    `gaia.cli.main._check_failure_operator_action`): every failure a
    first-time user can hit here names the file or command to look at next.
    """

    def __init__(self, message: str, operator_action: str) -> None:
        super().__init__(message)
        self.operator_action = operator_action


class DemoSeedError(DemoError):
    """A seeded run did not land in the status the demo promises."""


@dataclass(frozen=True)
class SeedRun:
    """One representative Run to create against the live `controlled-task` API."""

    label: str
    scenario_id: str
    text: str
    user_id: str
    organization: str
    roles: tuple[str, ...]
    # `None` means "no human gate is expected"; otherwise the decision the
    # demo's approver records against the gate the run creates.
    decision: str | None
    expected_status: str


@dataclass(frozen=True)
class SeedOutcome:
    plan: SeedRun
    run_id: str
    status: str


# Three runs, each demonstrating something a trivial success cannot:
#   1. A high-risk write that a human approved, and that then completed.
#   2. The same shape of write, refused by the human approver.
#   3. A read refused by policy before any human was ever asked.
# All three exercise the `controlled-task` reference scenario shipped at
# `examples/controlled_task/` (also used by `make dev-api`), using distinct
# resources so seeding one run cannot change the outcome of another.
SEED_PLAN: tuple[SeedRun, ...] = (
    SeedRun(
        label="controlled write, approved by a human and completed",
        scenario_id="controlled-task",
        text="pause res-001 because scheduled maintenance window",
        user_id="demo-operator",
        organization="org-alpha",
        roles=("operator",),
        decision="approved",
        expected_status="succeeded",
    ),
    SeedRun(
        label="controlled write, refused by a human approver",
        scenario_id="controlled-task",
        text="activate res-002 because customer requested early reactivation",
        user_id="demo-operator",
        organization="org-alpha",
        roles=("operator",),
        decision="rejected",
        expected_status="blocked",
    ),
    SeedRun(
        label="read refused by cross-organization policy, no human involved",
        scenario_id="controlled-task",
        text="inspect res-003",
        user_id="demo-reader",
        organization="org-alpha",
        roles=("reader",),
        decision=None,
        expected_status="blocked",
    ),
)


def seed_demo_runs(
    client: httpx.Client, plan: Sequence[SeedRun] = SEED_PLAN
) -> list[SeedOutcome]:
    """Create each `SeedRun` against `client` and decide its gate if it has one.

    `client` only needs `httpx.Client`'s `.post()`/`.get()` surface, which
    `starlette.testclient.TestClient` (a real `httpx.Client` subclass) also
    provides -- this is what lets `tests/integration/test_demo.py` exercise
    the exact same function in-process, against the exact same reference
    scenario, with no server or subprocess involved.
    """

    outcomes: list[SeedOutcome] = []
    for item in plan:
        idempotency_key = f"demo-{uuid.uuid4()}"
        response = client.post(
            "/v1/runs",
            headers={**API_KEY_HEADER, "Idempotency-Key": idempotency_key},
            json={
                "scenario_id": item.scenario_id,
                "mode": "mock",
                "user": {
                    "id": item.user_id,
                    "organization": item.organization,
                    "roles": list(item.roles),
                },
                "request": {"text": item.text},
            },
        )
        if response.status_code != 201:
            raise DemoSeedError(
                f"seeding '{item.label}' failed to create a run: "
                f"HTTP {response.status_code} {response.text}",
                "The controlled-task reference scenario may have changed shape; compare "
                "scripts/demo.py's SEED_PLAN against examples/controlled_task/workflow.py.",
            )
        run = response.json()
        run_id = run["run_id"]
        if item.decision is not None:
            run = _wait_for_run(
                client,
                run_id,
                expected_statuses={"waiting_human"},
                timeout_seconds=30,
            )
            gate_id = run.get("pending_gate_id")
            if not gate_id:
                raise DemoSeedError(
                    f"seeding '{item.label}' expected a pending human gate but none was created",
                    "Compare scripts/demo.py's SEED_PLAN against "
                    "examples/controlled_task/workflow.py -- the write may no longer require "
                    "approval for this resource and target status.",
                )
            decision_response = client.post(
                f"/v1/human-gates/{gate_id}/decision",
                headers=API_KEY_HEADER,
                json={
                    "decision": item.decision,
                    "decided_by": "demo-approver",
                    "roles": ["approver"],
                    "comment": f"make demo seed: {item.label}",
                },
            )
            if decision_response.status_code != 200:
                raise DemoSeedError(
                    f"seeding '{item.label}' could not record the human decision: "
                    f"HTTP {decision_response.status_code} {decision_response.text}",
                    "Re-run `make demo`; if this keeps happening, run "
                    "`uv run pytest tests/integration/test_demo.py -q` for a narrower failure.",
                )
        run = _wait_for_run(
            client,
            run_id,
            expected_statuses={item.expected_status},
            timeout_seconds=30,
        )
        if run["status"] != item.expected_status:
            raise DemoSeedError(
                f"seeding '{item.label}' produced status '{run['status']}', "
                f"expected '{item.expected_status}'",
                "The controlled-task reference scenario may have changed shape; run "
                "`uv run pytest tests/integration/test_demo.py -q` for a narrower failure.",
            )
        outcomes.append(SeedOutcome(plan=item, run_id=run["run_id"], status=run["status"]))
    return outcomes


def _wait_for_run(
    client: httpx.Client,
    run_id: str,
    *,
    expected_statuses: set[str],
    timeout_seconds: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        response = client.get(f"/v1/runs/{run_id}", headers=API_KEY_HEADER)
        if response.status_code != 200:
            raise DemoSeedError(
                f"could not read seeded run {run_id}: "
                f"HTTP {response.status_code} {response.text}",
                "Check the API and Temporal Worker output printed above.",
            )
        run = response.json()
        last_status = str(run["status"])
        if last_status in expected_statuses:
            return run
        time.sleep(0.2)
    raise DemoSeedError(
        f"run {run_id} stayed in '{last_status}' instead of reaching "
        f"{sorted(expected_statuses)} within {timeout_seconds:.0f}s",
        "Check the Temporal Server and Worker output printed above.",
    )


def run_migrations(database_path: Path) -> None:
    """Run every Alembic migration against `database_path` -- the real chain, not a shortcut.

    This is deliberately not `Base.metadata.create_all` (which the API's own
    startup would otherwise do for a brand-new SQLite file): the point of a
    demo is to exercise the same migration path a real deployment relies on,
    since a database that only ever saw `create_all` cannot show a broken
    migration.
    """

    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    try:
        command.upgrade(config, "head")
    except Exception as error:
        raise DemoError(
            f"could not migrate {database_path.name}: {error}",
            f"Delete {database_path} and re-run `make demo`; if it keeps failing, run "
            "`uv run pytest tests/integration/test_migrations.py -q` to check whether "
            "migrations are broken in general.",
        ) from error


def _reset_demo_database() -> None:
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for database_path in (DEMO_DB_PATH, DEMO_TEMPORAL_DB_PATH):
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)


def _start_temporal() -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "scripts/temporal_dev_server.py",
                "--host",
                DEMO_TEMPORAL_HOST,
                "--port",
                str(DEMO_TEMPORAL_PORT),
                "--database",
                str(DEMO_TEMPORAL_DB_PATH),
            ],
            cwd=ROOT,
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start Temporal: {error}",
            "Install `uv` (https://docs.astral.sh/uv/) and re-run `make demo`.",
        ) from error


def _demo_service_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["GAIA_API_KEY"] = DEMO_API_KEY
    env.setdefault("GAIA_DEVTOOLS_ENABLED", "true")
    env["GAIA_PROJECT_ROOT"] = str(ROOT)
    env["GAIA_DATABASE_URL"] = DEMO_DATABASE_URL
    return env


def _start_worker() -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            [
                "uv",
                "run",
                "gaia",
                "worker",
                "--config",
                "examples/controlled_task/gaia.yaml",
                "--app",
                "examples.controlled_task.app:create_app",
            ],
            cwd=ROOT,
            env=_demo_service_environment(),
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start the Temporal Worker: {error}",
            "Install `uv` (https://docs.astral.sh/uv/) and re-run `make demo`.",
        ) from error


def _start_api() -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "examples.controlled_task.app:create_app",
                "--factory",
                "--host",
                DEMO_API_HOST,
                "--port",
                str(DEMO_API_PORT),
            ],
            cwd=ROOT,
            env=_demo_service_environment(),
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start the API: {error}",
            "Install `uv` (https://docs.astral.sh/uv/) and re-run `make demo`.",
        ) from error


def _start_docs() -> subprocess.Popen[bytes]:
    """Start `mkdocs serve` the same way `make dev-docs` does.

    Docs are best-effort: `main()` treats a failure here as non-fatal (see
    the try/except around this call), so this function itself only needs to
    raise `DemoError` the same way every other `_start_*` helper does -- the
    difference in severity lives at the call site, not here.
    """

    try:
        return subprocess.Popen(
            [
                "uv",
                "run",
                "mkdocs",
                "serve",
                "--dev-addr",
                f"{DEMO_DOCS_HOST}:{DEMO_DOCS_PORT}",
            ],
            cwd=ROOT,
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start docs: {error}",
            "Install `uv` (https://docs.astral.sh/uv/) and re-run `make demo`.",
        ) from error


def _require_hr_showcase_prerequisite(path: Path, *, what: str, fix: str) -> None:
    """Fail fast with a readable message instead of a raw process-spawn error.

    The HR showcase (`docs/施工图/18-演示可用性施工图.md` D5) is a separate
    checkout with its own virtualenv and its own `node_modules` -- both of
    which a fresh clone of *this* repo will not have. Checking for them here
    (rather than letting `subprocess.Popen` fail with `FileNotFoundError`)
    lets the message name the exact missing prerequisite instead of a bare
    "no such file" for an interpreter path nobody typed by hand.
    """

    if not path.exists():
        raise DemoError(f"{what} not found at {path}", fix)


def _start_hr_backend() -> subprocess.Popen[bytes]:
    _require_hr_showcase_prerequisite(
        DEMO_HR_PYTHON,
        what="the HR showcase backend virtualenv",
        fix=f"Run `cd {DEMO_HR_BACKEND_ROOT} && uv sync`, then re-run `make demo`.",
    )
    try:
        return subprocess.Popen(
            [
                str(DEMO_HR_PYTHON),
                "-m",
                "uvicorn",
                "hr_showcase.app:app",
                "--host",
                DEMO_HR_API_HOST,
                "--port",
                str(DEMO_HR_API_PORT),
            ],
            cwd=DEMO_HR_BACKEND_ROOT,
            start_new_session=True,
        )
    except (FileNotFoundError, NotADirectoryError) as error:
        raise DemoError(
            f"could not start the HR showcase backend: {error}",
            f"Run `cd {DEMO_HR_BACKEND_ROOT} && uv sync`, then re-run `make demo`.",
        ) from error


def _start_hr_worker() -> subprocess.Popen[bytes]:
    _require_hr_showcase_prerequisite(
        DEMO_HR_GAIA_BIN,
        what="the HR showcase backend virtualenv's `gaia` command",
        fix=f"Run `cd {DEMO_HR_BACKEND_ROOT} && uv sync`, then re-run `make demo`.",
    )
    try:
        return subprocess.Popen(
            [
                str(DEMO_HR_GAIA_BIN),
                "worker",
                "--config",
                "gaia.yaml",
                "--app",
                "hr_showcase.app:create_app",
            ],
            cwd=DEMO_HR_BACKEND_ROOT,
            start_new_session=True,
        )
    except (FileNotFoundError, NotADirectoryError) as error:
        raise DemoError(
            f"could not start the HR showcase Temporal Worker: {error}",
            f"Run `cd {DEMO_HR_BACKEND_ROOT} && uv sync`, then re-run `make demo`.",
        ) from error


def _hr_frontend_environment(console_url: str) -> dict[str, str]:
    env = dict(os.environ)
    env["VITE_GAIA_CONSOLE_URL"] = console_url
    return env


def _start_hr_frontend(*, console_url: str) -> subprocess.Popen[bytes]:
    _require_hr_showcase_prerequisite(
        DEMO_HR_FRONTEND_ROOT / "node_modules",
        what="the HR showcase frontend's installed dependencies",
        fix=f"Run `cd {DEMO_HR_FRONTEND_ROOT} && npm install`, then re-run `make demo`.",
    )
    try:
        return subprocess.Popen(
            ["npm", "--prefix", str(DEMO_HR_FRONTEND_ROOT), "run", "dev"],
            cwd=ROOT,
            env=_hr_frontend_environment(console_url),
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start the HR showcase frontend: {error}",
            "Install Node.js, then re-run `make demo`.",
        ) from error


def _console_extra_env(
    *,
    docs_available: bool,
    docs_url: str,
    hr_showcase_available: bool,
    hr_showcase_url: str,
) -> dict[str, str]:
    """Tell the Console the truth about which linked services are running.

    Pulled out of `main()` as a pure function so the decision it encodes --
    not "how do I spawn a process" but "what does the Console get told" --
    can be tested directly instead of through a mocked `subprocess.Popen`.

    Both the HR showcase and docs are best-effort: when a service came up,
    the Console gets its live URL; when it did not, it gets an explicit
    "unavailable" flag instead of being left to guess from a failed request.
    For each service, exactly one of `<SERVICE>_URL` / `<SERVICE>_UNAVAILABLE`
    is ever set, so the Console can render a link only when the target is
    confirmed running -- never a plain link that errors when clicked. This
    also carries `VITE_GAIA_DEMO_MODE`, the flag `apps/web/src/Console.tsx`
    uses to land on `#demo` and hide 快速开始 (`docs/施工图/
    18-演示可用性施工图.md` D6) -- always true here because this function's
    only caller is `make demo`, never `gaia dev` / `make dev-console`.
    """

    env = {"VITE_GAIA_DEMO_MODE": "true"}
    if docs_available:
        env["VITE_GAIA_DOCS_URL"] = docs_url
    else:
        env["VITE_GAIA_DOCS_UNAVAILABLE"] = "true"
    if hr_showcase_available:
        env["VITE_GAIA_SHOWCASE_URL"] = hr_showcase_url
    else:
        env["VITE_GAIA_SHOWCASE_UNAVAILABLE"] = "true"
    return env


def _start_console(
    *, extra_env: dict[str, str], api_target: str
) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env["GAIA_API_KEY"] = DEMO_API_KEY
    env["VITE_GAIA_API_TARGET"] = api_target
    env.update(extra_env)
    try:
        return subprocess.Popen(
            [
                "npm",
                "--prefix",
                "apps/web",
                "run",
                "dev",
                "--",
                "--host",
                DEMO_CONSOLE_HOST,
                "--port",
                str(DEMO_CONSOLE_PORT),
                "--strictPort",
            ],
            cwd=ROOT,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DemoError(
            f"could not start the Console: {error}",
            "Run `make setup` to install the Console's dependencies "
            "(`npm --prefix apps/web ci`), then re-run `make demo`.",
        ) from error


def _wait_until_ready(
    url: str, *, process: subprocess.Popen[bytes], what: str, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise DemoError(
                f"{what} exited before it became ready (exit code {exit_code})",
                "Scroll up for its own startup output -- it was printed directly above.",
            )
        try:
            response = httpx.get(url, timeout=1.0)
        except httpx.TransportError as error:
            last_error = error
        else:
            if response.status_code < 500:
                return
            last_error = RuntimeError(f"HTTP {response.status_code}")
        time.sleep(0.3)
    raise DemoError(
        f"{what} did not become ready within {timeout_seconds:.0f}s at {url} ({last_error})",
        "Scroll up for its own startup output, or check whether another process is already "
        "using that port.",
    )


def _wait_until_port(
    host: str,
    port: int,
    *,
    process: subprocess.Popen[bytes],
    what: str,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise DemoError(
                f"{what} exited before it became ready (exit code {exit_code})",
                "Scroll up for its own startup output -- it was printed directly above.",
            )
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError as error:
            last_error = error
        time.sleep(0.3)
    raise DemoError(
        f"{what} did not listen on {host}:{port} within "
        f"{timeout_seconds:.0f}s ({last_error})",
        "Scroll up for its own startup output, or check whether another process "
        "is already using that port.",
    )


def _ensure_process_stays_running(
    process: subprocess.Popen[bytes],
    *,
    what: str,
    seconds: float,
) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise DemoError(
                f"{what} exited during startup (exit code {exit_code})",
                "Scroll up for its own startup output -- it was printed directly above.",
            )
        time.sleep(0.1)


def _wait_for_interrupt() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _terminate_on_signal(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    raise KeyboardInterrupt


def _shutdown(processes: list[subprocess.Popen[bytes]]) -> None:
    live = [process for process in processes if process.poll() is None]
    if not live:
        return
    print("\n[demo] stopping Temporal, Worker, API, Docs, and Console ...")
    for process in live:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in live:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    print("[demo] stopped.")


def main() -> int:
    # Stdout is only line-buffered by default when attached to a terminal --
    # redirected to a file or a log collector (as in CI, or `make demo |
    # tee ...`), CPython falls back to full block buffering, which would
    # hold every "[demo] ..." progress line (and the final URL) until the
    # process exits. This is the entire point of running the script, so it
    # must never wait for a buffer to fill.
    sys.stdout.reconfigure(line_buffering=True)
    signal.signal(signal.SIGTERM, _terminate_on_signal)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        print(f"[demo] preparing a disposable database at {DEMO_DB_PATH} ...")
        _reset_demo_database()
        run_migrations(DEMO_DB_PATH)

        print(
            f"[demo] starting Temporal on "
            f"{DEMO_TEMPORAL_HOST}:{DEMO_TEMPORAL_PORT} ..."
        )
        temporal_process = _start_temporal()
        processes.append(temporal_process)
        _wait_until_port(
            DEMO_TEMPORAL_HOST,
            DEMO_TEMPORAL_PORT,
            process=temporal_process,
            what="Temporal",
            timeout_seconds=60,
        )

        print("[demo] starting the controlled-task Temporal Worker ...")
        worker_process = _start_worker()
        processes.append(worker_process)
        _ensure_process_stays_running(
            worker_process,
            what="the Temporal Worker",
            seconds=2,
        )

        print(f"[demo] starting the API on http://{DEMO_API_HOST}:{DEMO_API_PORT} ...")
        api_process = _start_api()
        processes.append(api_process)
        _wait_until_ready(
            f"http://{DEMO_API_HOST}:{DEMO_API_PORT}/health/live",
            process=api_process,
            what="the API",
            timeout_seconds=30,
        )

        print("[demo] seeding runs worth looking at ...")
        with httpx.Client(
            base_url=f"http://{DEMO_API_HOST}:{DEMO_API_PORT}", timeout=10.0
        ) as client:
            outcomes = seed_demo_runs(client)
        for outcome in outcomes:
            print(f"  - {outcome.plan.label}: {outcome.status}")

        # Docs are best-effort: a demo with no documentation link is still a
        # demo; a demo that crashes because `mkdocs` is missing is not. A
        # failure here is caught (not re-raised) so the rest of `make demo`
        # still comes up -- the Console is told via `extra_env` below so its
        # sidebar link reflects reality instead of rendering a dead link.
        docs_url = f"http://{DEMO_DOCS_HOST}:{DEMO_DOCS_PORT}/"
        print(f"[demo] starting docs on {docs_url} ...")
        docs_available = True
        try:
            docs_process = _start_docs()
            processes.append(docs_process)
            _wait_until_ready(
                docs_url,
                process=docs_process,
                what="docs",
                timeout_seconds=30,
            )
        except DemoError as error:
            docs_available = False
            print(f"[demo] docs unavailable, continuing without them: {error}", file=sys.stderr)
            print(f"[demo] next step: {error.operator_action}", file=sys.stderr)

        # The HR showcase is a separate application living outside this repo.
        # Same best-effort contract as docs: a demo without it is still a demo,
        # and the Console is told which of the two it got, so its reference-app
        # cards are links only when something is actually listening.
        hr_showcase_url = f"http://{DEMO_HR_FRONTEND_HOST}:{DEMO_HR_FRONTEND_PORT}/"
        print(f"[demo] starting the HR showcase on {hr_showcase_url} ...")
        hr_showcase_available = True
        try:
            hr_backend = _start_hr_backend()
            processes.append(hr_backend)
            _wait_until_ready(
                f"http://{DEMO_HR_API_HOST}:{DEMO_HR_API_PORT}/health/live",
                process=hr_backend,
                what="the HR showcase backend",
                timeout_seconds=60,
            )
            # Its own task queue, so Temporal never hands controlled-task work
            # to a Worker that has none of those scenarios registered.
            hr_worker = _start_hr_worker()
            processes.append(hr_worker)
            hr_frontend = _start_hr_frontend(
                console_url=f"http://{DEMO_CONSOLE_HOST}:{DEMO_CONSOLE_PORT}/"
            )
            processes.append(hr_frontend)
            _wait_until_ready(
                hr_showcase_url,
                process=hr_frontend,
                what="the HR showcase frontend",
                timeout_seconds=60,
            )
        except DemoError as error:
            hr_showcase_available = False
            print(
                f"[demo] HR showcase unavailable, continuing without it: {error}",
                file=sys.stderr,
            )
            print(f"[demo] next step: {error.operator_action}", file=sys.stderr)

        console_extra_env = _console_extra_env(
            docs_available=docs_available,
            docs_url=docs_url,
            hr_showcase_available=hr_showcase_available,
            hr_showcase_url=hr_showcase_url,
        )

        print(f"[demo] starting the Console on http://{DEMO_CONSOLE_HOST}:{DEMO_CONSOLE_PORT} ...")
        console_api_target = (
            f"http://{DEMO_HR_API_HOST}:{DEMO_HR_API_PORT}"
            if hr_showcase_available
            else f"http://{DEMO_API_HOST}:{DEMO_API_PORT}"
        )
        console_process = _start_console(
            extra_env=console_extra_env,
            api_target=console_api_target,
        )
        processes.append(console_process)
        _wait_until_ready(
            f"http://{DEMO_CONSOLE_HOST}:{DEMO_CONSOLE_PORT}/",
            process=console_process,
            what="the Console",
            timeout_seconds=60,
        )

        console_url = f"http://{DEMO_CONSOLE_HOST}:{DEMO_CONSOLE_PORT}/#demo"
        print()
        if hr_showcase_available:
            print(
                f"Open {hr_showcase_url} to complete an HR task, then follow its "
                "Gaia evidence link into the Console."
            )
        else:
            print(f"Open {console_url} to see what Gaia is and what each seeded run proves.")
        if docs_available:
            print(f"Docs: {docs_url}")
        else:
            print("Docs: not started this run -- see the warning above.")
        if hr_showcase_available:
            print(f"HR reference application: {hr_showcase_url}")
        else:
            print(
                "HR reference application: not started this run -- see the warning above."
            )
        print()
        print("(Press Ctrl+C to stop all demo services.)")
        _wait_for_interrupt()
        return 0
    except DemoError as error:
        print(f"\n[demo] FAILED: {error}", file=sys.stderr)
        print(f"Next step: {error.operator_action}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        _shutdown(processes)


if __name__ == "__main__":
    sys.exit(main())
