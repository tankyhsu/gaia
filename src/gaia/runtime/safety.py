"""Non-bypassable admission and side-effect policy checks."""

from __future__ import annotations

from dataclasses import dataclass

from gaia.contracts.models import (
    ErrorCode,
    ExecutionPolicy,
    RunMode,
    RunRequest,
    ToolDefinition,
    ToolKind,
    WriteMode,
)
from gaia.runtime.dependencies import SideEffectProposal
from gaia.runtime.policy import (
    PolicyDenied,
    stricter_write_mode,
    validate_roles,
    validate_tool_allowed,
)


class SafetyViolation(ValueError):
    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(code.value)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SideEffectDecision:
    requires_approval: bool
    definition: ToolDefinition


def validate_run_admission(
    *,
    configured_environment: RunMode,
    request: RunRequest,
    policy: ExecutionPolicy,
) -> None:
    if request.mode != configured_environment:
        raise SafetyViolation(
            ErrorCode.ENVIRONMENT_MODE_MISMATCH,
            f"requested={request.mode.value}, configured={configured_environment.value}",
        )
    if policy.scenario_id != request.scenario_id:
        raise SafetyViolation(ErrorCode.POLICY_DENIED, "policy scenario does not match request")
    try:
        validate_roles(policy, request.user.roles)
    except PolicyDenied as error:
        raise SafetyViolation(ErrorCode.POLICY_DENIED, str(error)) from error


def evaluate_side_effect(
    *,
    configured_environment: RunMode,
    environment_write_mode: WriteMode,
    request: RunRequest,
    policy: ExecutionPolicy,
    proposal: SideEffectProposal,
    definition: ToolDefinition,
    risk_requires_approval: bool,
) -> SideEffectDecision:
    try:
        validate_tool_allowed(policy, proposal.tool_name)
    except PolicyDenied as error:
        raise SafetyViolation(ErrorCode.TOOL_NOT_ALLOWED, str(error)) from error
    if definition.name != proposal.tool_name or definition.kind != ToolKind.WRITE:
        raise SafetyViolation(ErrorCode.TOOL_DEFINITION_MISMATCH, proposal.tool_name)
    if configured_environment not in definition.allowed_environments:
        raise SafetyViolation(
            ErrorCode.TOOL_ENVIRONMENT_MISMATCH,
            f"{definition.name} cannot run in {configured_environment.value}",
        )
    missing_roles = set(definition.required_roles).difference(request.user.roles)
    if missing_roles:
        raise SafetyViolation(
            ErrorCode.TOOL_ROLE_REQUIRED,
            f"missing roles: {sorted(missing_roles)}",
        )
    if proposal.risk_level != definition.risk_level:
        raise SafetyViolation(
            ErrorCode.TOOL_DEFINITION_MISMATCH,
            "proposal risk does not match registered tool risk",
        )

    effective_mode = stricter_write_mode(environment_write_mode, policy.write_mode)
    if effective_mode == WriteMode.DISABLED:
        raise SafetyViolation(ErrorCode.WRITE_DISABLED, configured_environment.value)
    return SideEffectDecision(
        requires_approval=(effective_mode == WriteMode.APPROVAL_REQUIRED or risk_requires_approval),
        definition=definition,
    )
