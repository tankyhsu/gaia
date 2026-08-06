"""Pydantic models generated manually from the Gaia OpenAPI source of truth."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunMode(StrEnum):
    MOCK = "mock"
    SANDBOX = "sandbox"
    CUSTOMER = "customer"


class RunStatus(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActorType(StrEnum):
    MODEL = "model"
    RULE = "rule"
    TOOL = "tool"
    SYSTEM = "system"
    HUMAN = "human"


class EventStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class GateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class WriteMode(StrEnum):
    DISABLED = "disabled"
    APPROVAL_REQUIRED = "approval_required"
    ENABLED = "enabled"


class CommandStatus(StrEnum):
    PROPOSED = "proposed"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    # Terminal: automatic recovery exhausted its budget (or the write's
    # recovery strategy is `at_most_once_manual`, which has none) without
    # resolving the write's true outcome. This is an operator-visible marker
    # only -- there is deliberately no API to move a command out of this
    # status. See docs/施工图/13-重构施工图-装配打通与Runtime拆解.md task D1.1 and
    # developer-docs/mechanisms.md.
    NEEDS_ATTENTION = "needs_attention"


class ToolKind(StrEnum):
    READ = "read"
    WRITE = "write"


class WriteRecoveryStrategy(StrEnum):
    RECONCILABLE = "reconcilable"
    IDEMPOTENT = "idempotent"
    AT_MOST_ONCE_MANUAL = "at_most_once_manual"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ActionStatus(StrEnum):
    PENDING = "pending"
    WAITING_HUMAN = "waiting_human"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    SCENARIO_NOT_FOUND = "SCENARIO_NOT_FOUND"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    POLICY_DENIED = "POLICY_DENIED"
    ENVIRONMENT_MODE_MISMATCH = "ENVIRONMENT_MODE_MISMATCH"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    TOOL_ENVIRONMENT_MISMATCH = "TOOL_ENVIRONMENT_MISMATCH"
    TOOL_DEFINITION_MISMATCH = "TOOL_DEFINITION_MISMATCH"
    TOOL_ROLE_REQUIRED = "TOOL_ROLE_REQUIRED"
    TOOL_ADAPTER_ERROR = "TOOL_ADAPTER_ERROR"
    WRITE_DISABLED = "WRITE_DISABLED"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    MODEL_CAPABILITY_MISSING = "MODEL_CAPABILITY_MISSING"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"
    SIDE_EFFECT_UNKNOWN = "SIDE_EFFECT_UNKNOWN"
    HUMAN_GATE_REJECTED = "HUMAN_GATE_REJECTED"
    HUMAN_GATE_EXPIRED = "HUMAN_GATE_EXPIRED"
    # The Workflow says this gate was approved, but Gaia's audit projection --
    # the only store an authenticated approval is written to -- does not agree.
    GATE_DECISION_UNVERIFIED = "GATE_DECISION_UNVERIFIED"
    GATE_NOT_PENDING = "GATE_NOT_PENDING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    HANDOFF_NOT_ALLOWED = "HANDOFF_NOT_ALLOWED"
    HANDOFF_TARGET_NOT_FOUND = "HANDOFF_TARGET_NOT_FOUND"
    CONTINUATION_HANDLER_NOT_FOUND = "CONTINUATION_HANDLER_NOT_FOUND"
    RUN_NOT_RESUMABLE = "RUN_NOT_RESUMABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RUNTIME_ILLEGAL_TRANSITION = "RUNTIME_ILLEGAL_TRANSITION"
    POLICY_OVERRIDE_INVALID = "POLICY_OVERRIDE_INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    DURABLE_EXECUTION_REQUIRED = "DURABLE_EXECUTION_REQUIRED"


class ErrorCategory(StrEnum):
    REQUEST = "request"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONFIGURATION = "configuration"
    CONFLICT = "conflict"
    EXTERNAL_DEPENDENCY = "external_dependency"
    POLICY = "policy"
    RUNTIME = "runtime"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


class UserIdentity(ContractModel):
    id: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("roles must be unique")
        return value


class RunInput(ContractModel):
    text: str = Field(min_length=1, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRequest(ContractModel):
    scenario_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    mode: RunMode
    user: UserIdentity
    request: RunInput


class VersionBundle(ContractModel):
    policy: str
    workflow: str
    rules: str
    prompt: str
    model_profile: str
    toolset: str
    context_profile: str


class ErrorResponse(ContractModel):
    code: ErrorCode | str
    message: str
    trace_id: str
    category: ErrorCategory | str = ErrorCategory.UNKNOWN
    retryable: bool = False
    operator_action: str = "Inspect the diagnostic trace before retrying."
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalView(ContractModel):
    """Redacted business presentation for one human confirmation."""

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    fields: dict[str, Any] = Field(default_factory=dict)
    risk_explanation: str | None = Field(default=None, max_length=2000)


class PlannedActionSnapshot(ContractModel):
    step_id: str
    tool_name: str
    risk_level: RiskLevel
    status: ActionStatus
    depends_on: list[str] = Field(default_factory=list)
    command_id: str | None = None
    gate_id: str | None = None
    approval_view: ApprovalView | None = None
    result: dict[str, Any] | None = None
    error_code: ErrorCode | str | None = None


class ActionPlanSnapshot(ContractModel):
    version: Literal["1"] = "1"
    current_action: int = Field(default=0, ge=0)
    actions: list[PlannedActionSnapshot]


class HandoffSnapshot(ContractModel):
    current_agent: str
    reason: str
    handoff_count: int = Field(ge=1)


class ContinuationSnapshot(ContractModel):
    handler: str
    ready: bool


class RunSnapshot(ContractModel):
    run_id: str
    trace_id: str | None = None
    scenario_id: str
    mode: RunMode
    status: RunStatus
    user: UserIdentity
    version_bundle: VersionBundle
    pending_result: dict[str, Any] | None = None
    action_plan: ActionPlanSnapshot | None = None
    handoff: HandoffSnapshot | None = None
    continuation: ContinuationSnapshot | None = None
    result: dict[str, Any] | None = None
    error: ErrorResponse | None = None
    pending_gate_id: str | None = None
    created_at: datetime
    updated_at: datetime

    _created_at_utc = field_validator("created_at")(_utc)
    _updated_at_utc = field_validator("updated_at")(_utc)


class RunPage(ContractModel):
    """A page of `RunSnapshot`s, newest first.

    `next_cursor` is an opaque token: `None` means this is the last page.
    Pass it back as the `cursor` query parameter to fetch the next page.
    Do not parse or construct it -- its encoding is an implementation detail
    of the Runtime and may change without notice.
    """

    items: list[RunSnapshot]
    next_cursor: str | None = None


class RunEvent(ContractModel):
    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    actor: ActorType
    step: str
    status: EventStatus
    input_ref: str | None = None
    output_ref: str | None = None
    source_refs: list[str]
    rule_refs: list[str]
    error_code: ErrorCode | str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    _timestamp_utc = field_validator("timestamp")(_utc)


class HumanGate(ContractModel):
    gate_id: str
    run_id: str
    command_id: str
    reason: str
    risk_level: RiskLevel
    requested_action: dict[str, Any]
    approval_view: ApprovalView | None = None
    status: GateStatus
    requested_by: str
    decided_by: str | None = None
    comment: str | None = None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None

    _created_at_utc = field_validator("created_at")(_utc)
    _expires_at_utc = field_validator("expires_at")(_utc)
    _decided_at_utc = field_validator("decided_at")(_utc)


class HumanGateDecisionRequest(ContractModel):
    decision: Decision
    decided_by: str = Field(min_length=1)
    roles: list[str]
    comment: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def has_approver(self) -> HumanGateDecisionRequest:
        if "approver" not in self.roles:
            raise ValueError("roles must contain approver")
        return self


class CancelRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=1000)


class ReplayRequest(ContractModel):
    case_ids: list[str] | None = None
    all: bool = False

    @model_validator(mode="after")
    def exactly_one_selector(self) -> ReplayRequest:
        if (self.case_ids is None and not self.all) or (self.case_ids is not None and self.all):
            raise ValueError("provide case_ids or all=true")
        if self.case_ids is not None and len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids must be unique")
        return self


class ReplayCaseResult(ContractModel):
    case_id: str
    passed: bool
    expected_status: RunStatus
    actual_status: RunStatus
    assertions: list[dict[str, Any]]


class ReplaySnapshot(ContractModel):
    replay_id: str
    status: Literal["running", "completed", "failed"]
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: list[ReplayCaseResult]
    created_at: datetime
    finished_at: datetime | None = None

    _created_at_utc = field_validator("created_at")(_utc)
    _finished_at_utc = field_validator("finished_at")(_utc)


class ModelCapabilities(ContractModel):
    structured_output: bool
    tool_calling: bool
    streaming: bool
    max_context_tokens: int | None


class ModelHealth(ContractModel):
    provider_id: str
    model_id: str
    healthy: bool
    capabilities: ModelCapabilities
    checked_at: datetime
    error_code: ErrorCode | str | None = None

    _checked_at_utc = field_validator("checked_at")(_utc)


class ExecutionPolicy(ContractModel):
    policy_id: str
    version: str
    scenario_id: str
    allowed_tools: list[str]
    recognized_roles: list[str]
    max_steps: int = Field(ge=1)
    max_duration_seconds: int = Field(ge=1)
    max_model_calls: int = Field(ge=0)
    write_mode: WriteMode
    human_gate_rules: list[str]


class ContextDocument(ContractModel):
    source_id: str
    title: str
    version: str
    valid_until: datetime | None = None
    excerpt: str

    _valid_until_utc = field_validator("valid_until")(_utc)


class StructuredFact(ContractModel):
    source_system: str
    queried_at: datetime
    fields: dict[str, Any]

    _queried_at_utc = field_validator("queried_at")(_utc)


class ContextEnvelope(ContractModel):
    documents: list[ContextDocument]
    structured_facts: list[StructuredFact]
    access_scope: list[str]
    gaps: list[str]


class ToolDefinition(ContractModel):
    name: str
    version: str
    kind: ToolKind
    risk_level: RiskLevel
    required_roles: list[str]
    timeout_seconds: int = Field(ge=1)
    max_retries: int = Field(ge=0, le=1)
    idempotent: bool
    recovery_strategy: WriteRecoveryStrategy | None = None
    allowed_environments: list[RunMode] = Field(default_factory=lambda: [RunMode.MOCK])

    @field_validator("required_roles")
    @classmethod
    def unique_roles(cls, value: list[Any]) -> list[Any]:
        if len(value) != len(set(value)):
            raise ValueError("tool roles must be unique")
        return value

    @field_validator("allowed_environments")
    @classmethod
    def unique_non_empty_environments(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("tool environments must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("tool environments must be unique")
        return value


class ToolResult(ContractModel):
    ok: bool
    status: ToolResultStatus
    data: dict[str, Any]
    error_code: ErrorCode | str | None = None


class SideEffectCommand(ContractModel):
    command_id: str
    run_id: str
    step_id: str
    tool_name: str
    idempotency_key: str
    risk_level: RiskLevel
    payload_ref: str
    approval_ref: str | None = None
    result_ref: str | None = None
    status: CommandStatus
    created_at: datetime
    updated_at: datetime

    _created_at_utc = field_validator("created_at")(_utc)
    _updated_at_utc = field_validator("updated_at")(_utc)


class ModelEndpointProfile(ContractModel):
    provider_id: str
    protocol: Literal["openai-compatible", "mock"]
    base_url: str | None = None
    model_id: str
    artifact_version: str | None = None
    capabilities: ModelCapabilities
    data_residency: Literal["local", "customer_cloud", "external"]
    healthcheck_path: str | None = None
    timeout_seconds: int = Field(ge=1)


class HealthResponse(ContractModel):
    status: Literal["ok", "degraded", "unavailable"]
    checks: dict[str, str]


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    """Serialize a public input deterministically for idempotency hashing."""
    payload = (
        value.model_dump(mode="json", exclude_none=False) if isinstance(value, BaseModel) else value
    )
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def request_hash(value: RunRequest | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
