"""Small deterministic defaults; applications may replace every one of them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gaia.testing.models import GateContext, GateResult, Measurement, TestCase, TestObservation


def _contains(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping) or not _contains(actual_value, expected_value):
                return False
        elif actual_value != expected_value:
            return False
    return True


class ExpectedSubsetEvaluator:
    """Default hard assertion for structured outputs."""

    @property
    def evaluator_id(self) -> str:
        return "expected-subset"

    @property
    def evaluator_version(self) -> str:
        return "1.0.0"

    async def evaluate(self, case: TestCase, observation: TestObservation) -> Sequence[Measurement]:
        passed = observation.error_code is None and _contains(observation.actual, case.expected)
        return (
            Measurement(
                metric="expected_subset",
                value=passed,
                passed=passed,
                details={"error_code": observation.error_code},
            ),
        )


class RequiredMeasurementsGate:
    """Fail on executor/evaluator errors or any explicit failed measurement."""

    @property
    def gate_id(self) -> str:
        return "required-measurements"

    @property
    def gate_version(self) -> str:
        return "1.0.0"

    async def evaluate(self, context: GateContext) -> GateResult:
        executor_errors = [item.case_id for item in context.observations if item.error_code]
        evaluator_errors = [
            f"{item.case_id}:{item.evaluator_id}" for item in context.results if item.error
        ]
        failed = [
            f"{item.case_id}:{item.evaluator_id}:{item.measurement.metric}"
            for item in context.results
            if item.measurement.passed is False
        ]
        reasons = tuple(
            [*(f"executor_error:{case_id}" for case_id in executor_errors)]
            + [*(f"evaluator_error:{identifier}" for identifier in evaluator_errors)]
            + [*(f"measurement_failed:{identifier}" for identifier in failed)]
        )
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            passed=not reasons,
            reasons=reasons,
            details={
                "executor_errors": len(executor_errors),
                "evaluator_errors": len(evaluator_errors),
                "failed_measurements": len(failed),
            },
        )
