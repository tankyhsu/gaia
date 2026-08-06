"""Replay recorded Workflow Histories against the Workflow code as it stands now.

Temporal resumes a Workflow by replaying its recorded decision history against
the *current* code. If that code takes a different path than it did when the
history was written, the replay fails with a non-determinism error and the Run
is stuck -- it cannot advance, and for a Run parked on a HumanGate it cannot be
approved either.

That makes ordinary edits to `temporal_workflow.py` a deployment hazard rather
than a code change: Gaia's default gate TTL is a day, so "a Workflow is in
flight while a new version rolls out" is the normal case, not an edge case.

These fixtures are real histories from `test_temporal_end_to_end.py`, recorded
by `make capture-histories`. Replaying them here is the check that turns the
determinism rule into something CI can fail on. When this test breaks, the fix
is one of:

  * revert the Workflow change, or
  * guard the new branch with `workflow.patched(...)` so replays of old
    histories keep taking the old path, or
  * decide the change ships only to a new Worker build under pinned
    versioning, and re-record the fixtures.

Re-recording the fixtures to make this test pass is only correct in that last
case. Otherwise it deletes the evidence of the incompatibility.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from gaia.runtime.temporal_worker import gaia_workflow_runner
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow

HISTORY_FIXTURES = Path(__file__).parent / "histories"

# Each fixture is a distinct Workflow path. A history that only covers the happy
# path would let a change to gate handling or continuation resumption through.
EXPECTED_FIXTURES = {
    "read_only_scenario",
    "human_gate_approved",
    "langgraph_continuation",
    "audit_projection_write",
}


def _recorded_histories() -> list[tuple[str, WorkflowHistory]]:
    return [
        (path.stem, WorkflowHistory.from_json(path.stem, path.read_text(encoding="utf-8")))
        for path in sorted(HISTORY_FIXTURES.glob("*.json"))
    ]


def test_every_workflow_path_has_a_recorded_history() -> None:
    """A deleted fixture must fail loudly, not silently shrink the guard."""

    recorded = {name for name, _ in _recorded_histories()}
    missing = EXPECTED_FIXTURES - recorded
    assert not missing, (
        f"missing replay fixtures for {sorted(missing)}; "
        "run `make capture-histories` to record them"
    )


@pytest.mark.asyncio
async def test_recorded_histories_replay_against_current_workflow() -> None:
    """The current Workflow code must reach the same decisions as the recording."""

    histories = _recorded_histories()
    assert histories, "no replay fixtures found; run `make capture-histories`"
    replayer = Replayer(
        workflows=[GaiaRuntimeWorkflow],
        workflow_runner=gaia_workflow_runner(),
    )
    for name, history in histories:
        # One at a time, so a failure names the Workflow path that broke rather
        # than reporting that "a" history no longer replays.
        try:
            await replayer.replay_workflow(history)
        except Exception as error:  # noqa: BLE001 -- re-raised with the fixture name
            raise AssertionError(
                f"history fixture {name!r} no longer replays against the current "
                f"GaiaRuntimeWorkflow: {error}"
            ) from error
