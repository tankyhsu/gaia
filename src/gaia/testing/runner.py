"""Framework runner that coordinates cases, evaluators and release gates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gaia.testing.models import (
    EvaluationResult,
    GateContext,
    GateResult,
    Measurement,
    TestCase,
    TestDataset,
    TestObservation,
    TestReport,
)
from gaia.testing.protocols import CaseExecutor, Evaluator, QualityGate


class GaiaTestKit:
    def __init__(
        self,
        executor: CaseExecutor,
        *,
        evaluators: tuple[Evaluator, ...],
        gates: tuple[QualityGate, ...],
    ) -> None:
        if not evaluators:
            raise ValueError("at least one evaluator is required")
        if not gates:
            raise ValueError("at least one quality gate is required")
        if len({item.evaluator_id for item in evaluators}) != len(evaluators):
            raise ValueError("evaluator_id must be unique")
        if len({item.gate_id for item in gates}) != len(gates):
            raise ValueError("gate_id must be unique")
        self._executor = executor
        self._evaluators = evaluators
        self._gates = gates

    async def run(
        self,
        dataset: TestDataset,
        *,
        subject: dict[str, str] | None = None,
        repetitions: int = 1,
    ) -> TestReport:
        if repetitions < 1:
            raise ValueError("repetitions must be at least one")

        started_at = datetime.now(UTC)
        observations: list[TestObservation] = []
        results: list[EvaluationResult] = []
        for case in dataset.cases:
            for attempt in range(1, repetitions + 1):
                observation = await self._execute(case, attempt)
                observations.append(observation)
                for evaluator in self._evaluators:
                    try:
                        measurements = await evaluator.evaluate(case, observation)
                    except Exception as error:  # A broken evaluator is test evidence, not a crash.
                        results.append(
                            EvaluationResult(
                                case_id=case.case_id,
                                attempt=attempt,
                                evaluator_id=evaluator.evaluator_id,
                                evaluator_version=evaluator.evaluator_version,
                                measurement=Measurement(metric="evaluator_execution"),
                                error=f"{type(error).__name__}: {error}",
                            )
                        )
                        continue
                    if not measurements:
                        results.append(
                            EvaluationResult(
                                case_id=case.case_id,
                                attempt=attempt,
                                evaluator_id=evaluator.evaluator_id,
                                evaluator_version=evaluator.evaluator_version,
                                measurement=Measurement(metric="evaluator_execution"),
                                error="Evaluator returned no measurements",
                            )
                        )
                        continue
                    results.extend(
                        EvaluationResult(
                            case_id=case.case_id,
                            attempt=attempt,
                            evaluator_id=evaluator.evaluator_id,
                            evaluator_version=evaluator.evaluator_version,
                            measurement=measurement,
                        )
                        for measurement in measurements
                    )

        gate_context = GateContext(
            dataset=dataset,
            subject=subject or {},
            observations=tuple(observations),
            results=tuple(results),
        )
        gate_results = []
        for gate in self._gates:
            try:
                result = await gate.evaluate(gate_context)
                if result.gate_id != gate.gate_id or result.gate_version != gate.gate_version:
                    raise ValueError("gate returned a different id or version")
                gate_results.append(result)
            except Exception as error:
                gate_results.append(
                    GateResult(
                        gate_id=gate.gate_id,
                        gate_version=gate.gate_version,
                        passed=False,
                        reasons=("gate_execution_failed",),
                        error=f"{type(error).__name__}: {error}",
                    )
                )
        return TestReport(
            run_id=str(uuid4()),
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            subject=subject or {},
            repetitions=repetitions,
            observations=tuple(observations),
            results=tuple(results),
            gates=tuple(gate_results),
            passed=all(gate.passed for gate in gate_results),
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    async def _execute(self, case: TestCase, attempt: int) -> TestObservation:
        try:
            observation = await self._executor.execute(case, attempt=attempt)
        except Exception as error:  # Preserve the failure so gates and reporters can inspect it.
            return TestObservation(
                case_id=case.case_id,
                attempt=attempt,
                error_code="EXECUTOR_ERROR",
                evidence={"error": f"{type(error).__name__}: {error}"},
            )
        if observation.case_id != case.case_id or observation.attempt != attempt:
            raise ValueError("executor returned observation for a different case or attempt")
        return observation
