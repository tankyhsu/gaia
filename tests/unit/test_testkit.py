from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from gaia.testing import (
    EvaluationResult,
    ExpectedSubsetEvaluator,
    GaiaTestKit,
    GateContext,
    GateResult,
    Measurement,
    PassRateGate,
    RequiredMeasurementsGate,
    TestCase,
    TestDataset,
    TestObservation,
    load_dataset,
)


class EchoExecutor:
    async def execute(self, case: TestCase, *, attempt: int) -> TestObservation:
        return TestObservation(
            case_id=case.case_id,
            attempt=attempt,
            actual={"answer": case.input["answer"], "nested": {"source": "policy"}},
            evidence={"trace_id": f"{case.case_id}-{attempt}"},
        )


class CustomScoreEvaluator:
    @property
    def evaluator_id(self) -> str:
        return "custom-score"

    @property
    def evaluator_version(self) -> str:
        return "customer-model-3"

    async def evaluate(self, case: TestCase, observation: TestObservation) -> Sequence[Measurement]:
        return (
            Measurement(
                metric="customer_score",
                value=float(case.metadata["score"]),
                passed=None,
            ),
        )


class CustomAverageGate:
    @property
    def gate_id(self) -> str:
        return "customer-model"

    @property
    def gate_version(self) -> str:
        return "2.1.0"

    async def evaluate(self, context: GateContext) -> GateResult:
        values = [
            float(item.measurement.value)
            for item in context.results
            if item.evaluator_id == "custom-score"
        ]
        average = sum(values) / len(values)
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            passed=average >= 0.8,
            details={"average": average, "model": "application-defined"},
        )


def dataset() -> TestDataset:
    return TestDataset(
        dataset_id="public-contract-tests",
        version="2026-07-23",
        cases=(
            TestCase(
                case_id="case-a",
                input={"answer": "approved"},
                expected={"answer": "approved", "nested": {"source": "policy"}},
                metadata={"score": 0.9},
                tags=("hard-assertion",),
            ),
            TestCase(
                case_id="case-b",
                input={"answer": "rejected"},
                expected={"answer": "rejected"},
                metadata={"score": 0.7},
            ),
        ),
    )


@pytest.mark.asyncio
async def test_runs_repetitions_and_allows_application_defined_quality_model() -> None:
    kit = GaiaTestKit(
        EchoExecutor(),
        evaluators=(ExpectedSubsetEvaluator(), CustomScoreEvaluator()),
        gates=(RequiredMeasurementsGate(), CustomAverageGate()),
    )

    report = await kit.run(
        dataset(), subject={"application": "sample", "version": "2"}, repetitions=2
    )

    assert report.passed is True
    assert len(report.observations) == 4
    assert len(report.results) == 8
    assert report.subject == {"application": "sample", "version": "2"}
    assert report.gates[1].details == {"average": 0.8, "model": "application-defined"}
    assert {item.attempt for item in report.observations} == {1, 2}


class BrokenEvaluator:
    @property
    def evaluator_id(self) -> str:
        return "broken"

    @property
    def evaluator_version(self) -> str:
        return "1"

    async def evaluate(self, case: TestCase, observation: TestObservation) -> Sequence[Measurement]:
        raise RuntimeError("judge unavailable")


@pytest.mark.asyncio
async def test_evaluator_failure_is_evidence_and_fails_default_gate() -> None:
    kit = GaiaTestKit(
        EchoExecutor(),
        evaluators=(BrokenEvaluator(),),
        gates=(RequiredMeasurementsGate(),),
    )

    report = await kit.run(dataset())

    assert report.passed is False
    assert all(item.error == "RuntimeError: judge unavailable" for item in report.results)
    assert report.gates[0].details["evaluator_errors"] == 2


class BrokenExecutor:
    async def execute(self, case: TestCase, *, attempt: int) -> TestObservation:
        raise TimeoutError("model timeout")


@pytest.mark.asyncio
async def test_executor_failure_is_preserved_without_stopping_the_suite() -> None:
    kit = GaiaTestKit(
        BrokenExecutor(),
        evaluators=(ExpectedSubsetEvaluator(),),
        gates=(RequiredMeasurementsGate(),),
    )

    report = await kit.run(dataset())

    assert report.passed is False
    assert all(item.error_code == "EXECUTOR_ERROR" for item in report.observations)
    assert report.gates[0].details["executor_errors"] == 2


class BrokenGate:
    gate_id = "broken-gate"
    gate_version = "1"

    async def evaluate(self, context: GateContext) -> GateResult:
        raise RuntimeError("custom model failed")


@pytest.mark.asyncio
async def test_gate_failure_becomes_a_failed_report() -> None:
    kit = GaiaTestKit(
        EchoExecutor(),
        evaluators=(ExpectedSubsetEvaluator(),),
        gates=(BrokenGate(),),
    )

    report = await kit.run(dataset())

    assert report.passed is False
    assert report.gates[0].reasons == ("gate_execution_failed",)
    assert report.gates[0].error == "RuntimeError: custom model failed"


def test_dataset_rejects_duplicate_case_ids() -> None:
    case = TestCase(case_id="duplicate", input={})
    with pytest.raises(ValidationError, match="case_id must be unique"):
        TestDataset(dataset_id="dataset", version="1", cases=(case, case))


def test_evaluation_result_is_strict_and_serializable() -> None:
    result = EvaluationResult(
        case_id="case-a",
        attempt=1,
        evaluator_id="custom",
        evaluator_version="1",
        measurement=Measurement(metric="score", value=0.91),
    )
    assert result.model_dump(mode="json")["measurement"]["value"] == 0.91


def test_dataset_loader_accepts_versioned_json_and_yaml(tmp_path) -> None:
    payloads = {
        "dataset.json": """
            {"dataset_id":"golden","version":"1","cases":[
              {"case_id":"case-a","input":{"question":"hello"},"tags":["release"]}
            ]}
        """,
        "dataset.yaml": """
            dataset:
              dataset_id: golden
              version: "1"
              cases:
                - case_id: case-a
                  input:
                    question: hello
                  tags: [release]
        """,
    }
    for filename, content in payloads.items():
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        loaded = load_dataset(path)
        assert loaded.dataset_id == "golden"
        assert loaded.cases[0].tags == ("release",)


@pytest.mark.asyncio
async def test_pass_rate_gate_aggregates_repetitions_and_reports_slices() -> None:
    quality_gate = PassRateGate(
        evaluator_id="judge",
        metric="answer_quality",
        case_threshold=4,
        suite_threshold=2 / 3,
        attempt_policy="mean",
        critical_tags=("critical",),
        slice_thresholds={"boundary": 0.5},
    )
    test_dataset = TestDataset(
        dataset_id="golden",
        version="1",
        cases=(
            TestCase(case_id="a", input={}, tags=("critical",)),
            TestCase(case_id="b", input={}, tags=("boundary",)),
            TestCase(case_id="c", input={}),
        ),
    )
    scores = {"a": (4.0, 5.0), "b": (3.0, 5.0), "c": (2.0, 3.0)}
    results = tuple(
        EvaluationResult(
            case_id=case_id,
            attempt=attempt,
            evaluator_id="judge",
            evaluator_version="judge-v1",
            measurement=Measurement(metric="answer_quality", value=score),
        )
        for case_id, attempts in scores.items()
        for attempt, score in enumerate(attempts, start=1)
    )

    result = await quality_gate.evaluate(
        GateContext(dataset=test_dataset, observations=(), results=results)
    )

    assert result.passed is True
    assert result.details["pass_rate"] == 2 / 3
    assert result.details["slices"]["boundary"]["pass_rate"] == 1.0
    assert result.details["failed_case_ids"] == ["c"]


@pytest.mark.asyncio
async def test_pass_rate_gate_does_not_hide_missing_or_critical_failures() -> None:
    quality_gate = PassRateGate(
        evaluator_id="judge",
        metric="answer_quality",
        case_threshold=4,
        suite_threshold=0.3,
        critical_tags=("critical",),
        slice_thresholds={"boundary": 1.0},
    )
    test_dataset = TestDataset(
        dataset_id="golden",
        version="1",
        cases=(
            TestCase(case_id="critical", input={}, tags=("critical",)),
            TestCase(case_id="passing", input={}, tags=("boundary",)),
            TestCase(case_id="missing", input={}),
        ),
    )
    results = (
        EvaluationResult(
            case_id="critical",
            attempt=1,
            evaluator_id="judge",
            evaluator_version="judge-v1",
            measurement=Measurement(metric="answer_quality", value=2),
        ),
        EvaluationResult(
            case_id="passing",
            attempt=1,
            evaluator_id="judge",
            evaluator_version="judge-v1",
            measurement=Measurement(metric="answer_quality", value=5),
        ),
    )

    result = await quality_gate.evaluate(
        GateContext(dataset=test_dataset, observations=(), results=results)
    )

    assert result.passed is False
    assert result.reasons == ("missing_measurements", "critical_cases_failed")
    assert result.details["missing_case_ids"] == ["missing"]
