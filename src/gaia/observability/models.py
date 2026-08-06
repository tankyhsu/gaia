"""Read-only operational models for generic Gaia applications."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gaia.spi.model import ModelUsage as ModelUsage


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


class ToolInvocationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"


class ToolInvocation(BaseModel):
    """Payload-free evidence for one run-scoped tool call."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    run_id: str
    scenario_id: str
    tool_name: str
    tool_version: str
    status: ToolInvocationStatus
    input_ref: str
    output_ref: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    error_code: str | None = None

    @model_validator(mode="after")
    def status_has_consistent_evidence(self) -> ToolInvocation:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.status == ToolInvocationStatus.SUCCEEDED and self.output_ref is None:
            raise ValueError("a successful tool invocation requires output_ref")
        if self.status != ToolInvocationStatus.SUCCEEDED and self.error_code is None:
            raise ValueError("an unsuccessful tool invocation requires error_code")
        return self


class ToolInvocationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    succeeded: int
    failed: int
    blocked: int
    timed_out: int
    duration: DurationSummary


class RunToolObservability(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    summary: ToolInvocationSummary
    invocations: tuple[ToolInvocation, ...]


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
    trace_id: str | None = None
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
    # Runs a control deliberately refused: an approver rejecting a write, a
    # policy denying a tool. Reported as its own number because it is neither a
    # success nor a failure, and presenting it as either misrepresents what
    # happened -- see `stopped_by_control` in observability/runtime.py.
    stopped_by_control: int
    active_runs: int
    stale_runs: int
    pending_human_gates: int
    oldest_pending_gate_age_seconds: int | None
    run_duration: DurationSummary
    human_gate_wait: DurationSummary
    error_counts: dict[str, int]
    database: DatabaseContention
    outbox: OutboxSummary
    # Commands parked in the terminal `needs_attention` status (task card D1.1
    # in docs/施工图/13-重构施工图-装配打通与Runtime拆解.md): automatic recovery
    # exhausted its budget without resolving the write's true outcome, and
    # there is deliberately no API to move a command out of this status --
    # only a human, working from the downstream system of record, can. This
    # count is how an operator finds out one exists at all.
    needs_attention: int
    issues: tuple[RuntimeIssue, ...]
