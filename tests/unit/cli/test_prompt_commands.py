from datetime import UTC, datetime
from pathlib import Path

import pytest

from gaia.cli.prompts import validation_from_report
from gaia.spi.prompt import PromptArtifact
from gaia.testing.models import GateResult, TestReport


def artifact() -> PromptArtifact:
    return PromptArtifact(
        prompt_id="summary",
        version="1.0.0",
        messages=({"role": "system", "content": "Summarize."},),
    )


def report(value: PromptArtifact, *, passed: bool = True) -> TestReport:
    now = datetime.now(UTC)
    return TestReport(
        run_id="report-1",
        dataset_id="summary-golden",
        dataset_version="3",
        subject={
            "prompt_id": value.prompt_id,
            "prompt_version": value.version,
            "prompt_content_hash": value.content_hash,
        },
        repetitions=1,
        observations=(),
        results=(),
        gates=(
            GateResult(
                gate_id="pass-rate",
                gate_version="1.0.0",
                passed=passed,
            ),
        ),
        passed=passed,
        started_at=now,
        finished_at=now,
    )


def test_validation_requires_passing_report_bound_to_exact_artifact(tmp_path: Path) -> None:
    value = artifact()
    path = tmp_path / "report.json"
    path.write_text(report(value).model_dump_json(), encoding="utf-8")

    evidence = validation_from_report(path, value)

    assert evidence.passed is True
    assert evidence.report_id == "report-1"
    assert evidence.gate_ids == ("pass-rate",)

    path.write_text(
        report(value)
        .model_copy(
            update={
                "subject": {
                    **report(value).subject,
                    "prompt_content_hash": "wrong",
                }
            }
        )
        .model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="subject mismatch"):
        validation_from_report(path, value)


def test_validation_rejects_failed_report(tmp_path: Path) -> None:
    value = artifact()
    path = tmp_path / "report.json"
    path.write_text(report(value, passed=False).model_dump_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="did not pass"):
        validation_from_report(path, value)
