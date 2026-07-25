import pytest

from gaia.contracts.models import RunStatus
from gaia.runtime.lifecycle import InvalidStateTransition, validate_transition


def test_lifecycle_permits_only_documented_transitions() -> None:
    validate_transition(RunStatus.RECEIVED, RunStatus.VALIDATED)
    validate_transition(RunStatus.RUNNING, RunStatus.WAITING_HUMAN)
    with pytest.raises(InvalidStateTransition):
        validate_transition(RunStatus.SUCCEEDED, RunStatus.RUNNING)
