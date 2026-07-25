"""Gaia-owned SQLAlchemy tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    user_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version_bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pending_gate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunEventRecord(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rule_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class HumanGateRecord(Base):
    __tablename__ = "human_gates"

    gate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_action: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SideEffectCommandRecord(Base):
    __tablename__ = "side_effect_commands"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    approval_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelInvocationRecord(Base):
    __tablename__ = "model_invocations"
    __table_args__ = (
        Index("ix_model_invocations_run", "run_id", "started_at"),
        Index("ix_model_invocations_status", "status", "started_at"),
    )

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"), nullable=True)
    scenario_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    model_parameters_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt_content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    response_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_token_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GuardrailDecisionRecord(Base):
    __tablename__ = "guardrail_decisions"
    __table_args__ = (
        Index("ix_guardrail_decisions_run", "run_id", "started_at"),
        Index("ix_guardrail_decisions_stage", "stage", "action", "started_at"),
    )

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"), nullable=True)
    scenario_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    guardrail_id: Mapped[str] = mapped_column(String(128), nullable=False)
    guardrail_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    output_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class ReplayJobRecord(Base):
    __tablename__ = "replay_jobs"

    replay_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReplayCaseResultRecord(Base):
    __tablename__ = "replay_case_results"
    __table_args__ = (Index("ix_replay_case_results_replay_id", "replay_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    replay_id: Mapped[str] = mapped_column(ForeignKey("replay_jobs.replay_id"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    expected_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_status: Mapped[str] = mapped_column(String(32), nullable=False)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_delivery", "status", "available_at", "created_at"),
        Index("ix_outbox_events_lock", "locked_until"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    headers_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromptVersionRecord(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "content_hash", name="uq_prompt_version_content"),
        Index("ix_prompt_versions_status", "status", "updated_at"),
    )

    prompt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptReleaseRecord(Base):
    __tablename__ = "prompt_releases"

    prompt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptAuditRecord(Base):
    __tablename__ = "prompt_audits"
    __table_args__ = (Index("ix_prompt_audits_prompt", "prompt_id", "created_at"),)

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
