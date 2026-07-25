"""Reusable release gates for dataset-level AI application quality decisions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from gaia.testing.models import EvaluationResult, GateContext, GateResult, TestCase

AttemptPolicy = Literal["all", "any", "mean"]
ScoreOperator = Literal["gte", "lte"]


class PassRateGate:
    """Require a case-level pass rate, with optional critical and slice thresholds."""

    def __init__(
        self,
        *,
        evaluator_id: str,
        metric: str,
        suite_threshold: float,
        case_threshold: float | None = None,
        score_operator: ScoreOperator = "gte",
        attempt_policy: AttemptPolicy = "all",
        minimum_cases: int = 1,
        include_tags: Sequence[str] = (),
        critical_tags: Sequence[str] = (),
        slice_thresholds: Mapping[str, float] | None = None,
        gate_id: str = "pass-rate",
        gate_version: str = "1.0.0",
    ) -> None:
        if not evaluator_id or not metric:
            raise ValueError("evaluator_id and metric are required")
        if not gate_id or not gate_version:
            raise ValueError("gate_id and gate_version are required")
        if score_operator not in {"gte", "lte"}:
            raise ValueError("score_operator must be gte or lte")
        if attempt_policy not in {"all", "any", "mean"}:
            raise ValueError("attempt_policy must be all, any, or mean")
        _validate_rate("suite_threshold", suite_threshold)
        if case_threshold is not None and not math.isfinite(case_threshold):
            raise ValueError("case_threshold must be finite")
        if minimum_cases < 1:
            raise ValueError("minimum_cases must be at least one")
        if attempt_policy == "mean" and case_threshold is None:
            raise ValueError("mean attempt_policy requires case_threshold")
        thresholds = dict(slice_thresholds or {})
        for tag, threshold in thresholds.items():
            if not tag:
                raise ValueError("slice tag cannot be empty")
            _validate_rate(f"slice_thresholds[{tag}]", threshold)

        self._evaluator_id = evaluator_id
        self._metric = metric
        self._suite_threshold = suite_threshold
        self._case_threshold = case_threshold
        self._score_operator = score_operator
        self._attempt_policy = attempt_policy
        self._minimum_cases = minimum_cases
        self._include_tags = frozenset(include_tags)
        self._critical_tags = frozenset(critical_tags)
        self._slice_thresholds = thresholds
        self._gate_id = gate_id
        self._gate_version = gate_version

    @property
    def gate_id(self) -> str:
        return self._gate_id

    @property
    def gate_version(self) -> str:
        return self._gate_version

    async def evaluate(self, context: GateContext) -> GateResult:
        cases = [
            case
            for case in context.dataset.cases
            if not self._include_tags or self._include_tags.intersection(case.tags)
        ]
        outcomes = {case.case_id: self._case_outcome(case, context.results) for case in cases}
        summary = _summarize(cases, outcomes)
        reasons: list[str] = []

        if len(cases) < self._minimum_cases:
            reasons.append("insufficient_cases")
        if summary["missing_cases"]:
            reasons.append("missing_measurements")
        if cast(float, summary["pass_rate"]) < self._suite_threshold:
            reasons.append("pass_rate_below_threshold")

        critical_cases = [case for case in cases if self._critical_tags.intersection(case.tags)]
        critical_summary = _summarize(critical_cases, outcomes)
        if critical_cases and cast(float, critical_summary["pass_rate"]) < 1.0:
            reasons.append("critical_cases_failed")

        slices: dict[str, dict[str, object]] = {}
        for tag, threshold in self._slice_thresholds.items():
            tagged_cases = [case for case in cases if tag in case.tags]
            slice_summary = _summarize(tagged_cases, outcomes)
            slice_summary["required_pass_rate"] = threshold
            slices[tag] = slice_summary
            if not tagged_cases:
                reasons.append(f"slice_missing:{tag}")
            elif cast(float, slice_summary["pass_rate"]) < threshold:
                reasons.append(f"slice_below_threshold:{tag}")

        details = {
            **summary,
            "required_pass_rate": self._suite_threshold,
            "minimum_cases": self._minimum_cases,
            "evaluator_id": self._evaluator_id,
            "metric": self._metric,
            "case_threshold": self._case_threshold,
            "score_operator": self._score_operator,
            "attempt_policy": self._attempt_policy,
            "critical": critical_summary,
            "slices": slices,
        }
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            passed=not reasons,
            reasons=tuple(reasons),
            details=details,
        )

    def _case_outcome(self, case: TestCase, results: tuple[EvaluationResult, ...]) -> bool | None:
        evaluator_results = [
            item
            for item in results
            if item.case_id == case.case_id and item.evaluator_id == self._evaluator_id
        ]
        if any(item.error for item in evaluator_results):
            return None
        measurements = [
            item.measurement
            for item in evaluator_results
            if item.measurement.metric == self._metric
        ]
        if not measurements:
            return None

        if self._case_threshold is not None:
            numeric_values = [
                float(item.value)
                for item in measurements
                if isinstance(item.value, int | float)
                and not isinstance(item.value, bool)
                and math.isfinite(float(item.value))
            ]
            if len(numeric_values) != len(measurements):
                return None
            if self._attempt_policy == "mean":
                return self._compare(sum(numeric_values) / len(numeric_values))
            attempts = [self._compare(value) for value in numeric_values]
        else:
            if any(item.passed is None for item in measurements):
                return None
            attempts = [bool(item.passed) for item in measurements]

        return all(attempts) if self._attempt_policy == "all" else any(attempts)

    def _compare(self, value: float) -> bool:
        assert self._case_threshold is not None
        if self._score_operator == "gte":
            return value >= self._case_threshold
        return value <= self._case_threshold


def _summarize(cases: Sequence[TestCase], outcomes: Mapping[str, bool | None]) -> dict[str, object]:
    passed = [case.case_id for case in cases if outcomes.get(case.case_id) is True]
    failed = [case.case_id for case in cases if outcomes.get(case.case_id) is False]
    missing = [case.case_id for case in cases if outcomes.get(case.case_id) is None]
    total = len(cases)
    return {
        "total_cases": total,
        "evaluated_cases": len(passed) + len(failed),
        "passed_cases": len(passed),
        "failed_cases": len(failed),
        "missing_cases": len(missing),
        "pass_rate": len(passed) / total if total else 0.0,
        "failed_case_ids": failed,
        "missing_case_ids": missing,
    }


def _validate_rate(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between zero and one")
