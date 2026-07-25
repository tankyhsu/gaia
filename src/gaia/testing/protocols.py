"""Extension protocols for application-specific execution and quality models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from gaia.testing.models import GateContext, GateResult, Measurement, TestCase, TestObservation


class CaseExecutor(Protocol):
    async def execute(self, case: TestCase, *, attempt: int) -> TestObservation: ...


class Evaluator(Protocol):
    @property
    def evaluator_id(self) -> str: ...

    @property
    def evaluator_version(self) -> str: ...

    async def evaluate(
        self, case: TestCase, observation: TestObservation
    ) -> Sequence[Measurement]: ...


class QualityGate(Protocol):
    @property
    def gate_id(self) -> str: ...

    @property
    def gate_version(self) -> str: ...

    async def evaluate(self, context: GateContext) -> GateResult: ...
