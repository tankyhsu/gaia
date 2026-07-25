"""Stable, application-neutral contracts for Gaia Test Kit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TestContract(BaseModel):
    __test__: ClassVar[bool] = False
    model_config = ConfigDict(extra="forbid", frozen=True)


class TestCase(TestContract):
    case_id: str = Field(min_length=1)
    input: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()


class TestDataset(TestContract):
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: tuple[TestCase, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> TestDataset:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id must be unique within a dataset")
        return self


class TestObservation(TestContract):
    case_id: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    actual: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)


class Measurement(TestContract):
    metric: str = Field(min_length=1)
    value: bool | int | float | str | None = None
    passed: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(TestContract):
    case_id: str
    attempt: int = Field(ge=1)
    evaluator_id: str
    evaluator_version: str
    measurement: Measurement
    error: str | None = None


class GateContext(TestContract):
    dataset: TestDataset
    subject: dict[str, str] = Field(default_factory=dict)
    observations: tuple[TestObservation, ...]
    results: tuple[EvaluationResult, ...]


class GateResult(TestContract):
    gate_id: str = Field(min_length=1)
    gate_version: str = Field(min_length=1)
    passed: bool
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TestReport(TestContract):
    run_id: str
    dataset_id: str
    dataset_version: str
    subject: dict[str, str] = Field(default_factory=dict)
    repetitions: int = Field(ge=1)
    observations: tuple[TestObservation, ...]
    results: tuple[EvaluationResult, ...]
    gates: tuple[GateResult, ...]
    passed: bool
    started_at: datetime
    finished_at: datetime

    @field_validator("started_at", "finished_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include timezone")
        return value.astimezone(UTC)
