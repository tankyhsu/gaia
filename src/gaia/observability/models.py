"""Read-only operational models for generic Gaia applications."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gaia.sdk.model import ModelUsage as ModelUsage


class ModelInvocationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelInvocation(BaseModel):
    """Safe engineering evidence for one model call, excluding private reasoning."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    run_id: str
    scenario_id: str
    provider: str
    model_id: str
    model_parameters_hash: str
    prompt_version: str
    prompt_content_hash: str | None = None
    request_ref: str
    response_ref: str | None = None
    status: ModelInvocationStatus
    usage: ModelUsage | None = None
    started_at: datetime
    completed_at: datetime
    first_token_latency_ms: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = None

    @model_validator(mode="after")
    def status_has_consistent_evidence(self) -> ModelInvocation:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.status == ModelInvocationStatus.SUCCEEDED and self.response_ref is None:
            raise ValueError("a successful invocation requires response_ref")
        if self.status == ModelInvocationStatus.FAILED and self.error_code is None:
            raise ValueError("a failed invocation requires error_code")
        return self


class DurationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    average_ms: int | None = None
    p50_ms: int | None = None
    p95_ms: int | None = None


class ModelInvocationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    succeeded: int
    failed: int
    retry_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_by_currency: dict[str, float] = Field(default_factory=dict)
    duration: DurationSummary


class RunModelObservability(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    summary: ModelInvocationSummary
    invocations: tuple[ModelInvocation, ...]


class DatabaseContention(BaseModel):
    model_config = ConfigDict(frozen=True)
    backend: str
    pool_class: str
    pool_size: int | None = None
    checked_out: int | None = None
    overflow: int | None = None
    waiting_connections: int | None = None
    lock_waiting_connections: int | None = None


class OutboxSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    status_counts: dict[str, int] = Field(default_factory=dict)
    pending: int = 0
    retrying: int = 0
    dead_letter: int = 0


class RuntimeIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    scenario_id: str
    status: str
    bottleneck: str
    age_seconds: int
    error_code: str | None = None
    updated_at: datetime


class RuntimeSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    window_hours: int
    stale_after_seconds: int
    generated_at: datetime
    total_runs: int
    status_counts: dict[str, int]
    success_rate: float
    failure_rate: float
    blocked_rate: float
    active_runs: int
    stale_runs: int
    pending_human_gates: int
    oldest_pending_gate_age_seconds: int | None
    run_duration: DurationSummary
    human_gate_wait: DurationSummary
    error_counts: dict[str, int]
    database: DatabaseContention
    outbox: OutboxSummary
    issues: tuple[RuntimeIssue, ...]
