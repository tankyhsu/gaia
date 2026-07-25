"""Stable machine codes with human-readable operational guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gaia.contracts.models import ErrorCategory, ErrorCode, ErrorResponse


@dataclass(frozen=True)
class ErrorDescriptor:
    message: str
    category: ErrorCategory
    retryable: bool
    operator_action: str


_DEFAULT = ErrorDescriptor(
    message="The request could not be completed.",
    category=ErrorCategory.UNKNOWN,
    retryable=False,
    operator_action="Use the trace ID to inspect diagnostics before retrying.",
)


_CATALOG: dict[str, ErrorDescriptor] = {
    ErrorCode.INVALID_REQUEST.value: ErrorDescriptor(
        "The request does not match the required schema.",
        ErrorCategory.REQUEST,
        False,
        "Correct the reported fields and submit the request again.",
    ),
    ErrorCode.SCENARIO_NOT_FOUND.value: ErrorDescriptor(
        "The requested scenario is not registered.",
        ErrorCategory.CONFIGURATION,
        False,
        "Check the scenario ID and the application runner registration.",
    ),
    ErrorCode.IDEMPOTENCY_CONFLICT.value: ErrorDescriptor(
        "This idempotency key was already used for different input.",
        ErrorCategory.CONFLICT,
        False,
        "Reuse the original input or submit the new input with a new idempotency key.",
    ),
    ErrorCode.UNAUTHORIZED.value: ErrorDescriptor(
        "Authentication is missing or invalid.",
        ErrorCategory.AUTHENTICATION,
        False,
        "Provide a valid Gaia API key.",
    ),
    ErrorCode.FORBIDDEN.value: ErrorDescriptor(
        "The caller does not have permission to perform this action.",
        ErrorCategory.AUTHORIZATION,
        False,
        "Check the caller identity, role, and data scope.",
    ),
    ErrorCode.POLICY_DENIED.value: ErrorDescriptor(
        "The current policy does not allow this action.",
        ErrorCategory.POLICY,
        False,
        "Review the policy decision and the caller role before changing any rule.",
    ),
    ErrorCode.ENVIRONMENT_MODE_MISMATCH.value: ErrorDescriptor(
        "The request mode does not match the server environment.",
        ErrorCategory.CONFIGURATION,
        False,
        "Use the server-owned environment shown by Actuator or deploy the intended profile.",
    ),
    ErrorCode.TOOL_NOT_REGISTERED.value: ErrorDescriptor(
        "The requested tool is not registered in this application.",
        ErrorCategory.CONFIGURATION,
        False,
        "Register the tool and verify the active Starter and profile.",
    ),
    ErrorCode.TOOL_NOT_ALLOWED.value: ErrorDescriptor(
        "The current scenario does not allow this tool.",
        ErrorCategory.POLICY,
        False,
        "Review the scenario tool allowlist and policy.",
    ),
    ErrorCode.TOOL_ENVIRONMENT_MISMATCH.value: ErrorDescriptor(
        "The tool is not allowed in the current environment.",
        ErrorCategory.CONFIGURATION,
        False,
        "Bind an adapter that explicitly supports the active environment.",
    ),
    ErrorCode.TOOL_DEFINITION_MISMATCH.value: ErrorDescriptor(
        "The tool adapter does not match its registered definition.",
        ErrorCategory.CONFIGURATION,
        False,
        "Compare the adapter definition with the registered tool contract.",
    ),
    ErrorCode.TOOL_ROLE_REQUIRED.value: ErrorDescriptor(
        "The caller is missing a role required by this tool.",
        ErrorCategory.AUTHORIZATION,
        False,
        "Use an authorized identity or update the tool policy through review.",
    ),
    ErrorCode.TOOL_ADAPTER_ERROR.value: ErrorDescriptor(
        "The external tool adapter failed.",
        ErrorCategory.EXTERNAL_DEPENDENCY,
        True,
        "Inspect the adapter health and trace, then retry only when the side effect is known.",
    ),
    ErrorCode.WRITE_DISABLED.value: ErrorDescriptor(
        "Writes are disabled in the current environment.",
        ErrorCategory.POLICY,
        False,
        "Use an approved environment and write policy; do not bypass the runtime boundary.",
    ),
    ErrorCode.CONTEXT_INSUFFICIENT.value: ErrorDescriptor(
        "The available context is not sufficient for a reliable result.",
        ErrorCategory.RUNTIME,
        False,
        "Review source coverage and retrieval evidence before continuing.",
    ),
    ErrorCode.MODEL_CAPABILITY_MISSING.value: ErrorDescriptor(
        "The configured model endpoint lacks a required capability.",
        ErrorCategory.CONFIGURATION,
        False,
        "Select a compatible model profile or reduce the required capability set.",
    ),
    ErrorCode.MODEL_UNAVAILABLE.value: ErrorDescriptor(
        "The model service is unavailable or timed out.",
        ErrorCategory.EXTERNAL_DEPENDENCY,
        True,
        "Check the model endpoint and credentials, then retry after service recovery.",
    ),
    ErrorCode.TOOL_TIMEOUT.value: ErrorDescriptor(
        "The external tool did not respond before the timeout.",
        ErrorCategory.EXTERNAL_DEPENDENCY,
        True,
        "Check tool health and latency before retrying.",
    ),
    ErrorCode.SIDE_EFFECT_UNKNOWN.value: ErrorDescriptor(
        "The write result is unknown and automatic retry is unsafe.",
        ErrorCategory.RUNTIME,
        False,
        "Reconcile the target system before approving any retry.",
    ),
    ErrorCode.HUMAN_GATE_REJECTED.value: ErrorDescriptor(
        "The pending action was rejected by an approver.",
        ErrorCategory.POLICY,
        False,
        "Review the decision comment and revise the proposed action.",
    ),
    ErrorCode.HUMAN_GATE_EXPIRED.value: ErrorDescriptor(
        "The approval request expired before a decision was made.",
        ErrorCategory.RUNTIME,
        False,
        "Review the run and create a new approval request if the action is still valid.",
    ),
    ErrorCode.BUDGET_EXCEEDED.value: ErrorDescriptor(
        "The run exceeded its configured execution budget.",
        ErrorCategory.RUNTIME,
        False,
        "Inspect step, model-call, and duration limits before adjusting the policy.",
    ),
    ErrorCode.RUN_NOT_RESUMABLE.value: ErrorDescriptor(
        "The run is not in a resumable state.",
        ErrorCategory.CONFLICT,
        False,
        "Refresh the run state and only resume a supported waiting state.",
    ),
    ErrorCode.INTERNAL_ERROR.value: ErrorDescriptor(
        "The application failed while processing the run.",
        ErrorCategory.INTERNAL,
        True,
        "Use the trace ID and diagnostic bundle to identify the failing component.",
    ),
    "RUNTIME_UNAVAILABLE": ErrorDescriptor(
        "This application has not installed runtime dependencies.",
        ErrorCategory.CONFIGURATION,
        False,
        "Install an application runtime composition before using Run APIs.",
    ),
    "PROMPT_NOT_AVAILABLE": ErrorDescriptor(
        "No published Prompt version is available for this scenario and environment.",
        ErrorCategory.CONFIGURATION,
        False,
        "Publish a validated Prompt version or correct the scenario Prompt selector.",
    ),
    "PROMPT_PROVIDER_UNAVAILABLE": ErrorDescriptor(
        "The Prompt provider is unavailable.",
        ErrorCategory.EXTERNAL_DEPENDENCY,
        True,
        "Check the Prompt Registry connection and retry after it recovers.",
    ),
    "RUN_NOT_FOUND": ErrorDescriptor(
        "The requested run does not exist.",
        ErrorCategory.REQUEST,
        False,
        "Check the run ID and application environment.",
    ),
    "GATE_NOT_FOUND": ErrorDescriptor(
        "The requested approval gate does not exist.",
        ErrorCategory.REQUEST,
        False,
        "Refresh the run and use its current pending gate ID.",
    ),
    "REPLAY_NOT_FOUND": ErrorDescriptor(
        "The requested replay does not exist.",
        ErrorCategory.REQUEST,
        False,
        "Check the replay ID and application environment.",
    ),
    "RUN_NOT_CANCELLABLE": ErrorDescriptor(
        "The run has already reached a state that cannot be cancelled.",
        ErrorCategory.CONFLICT,
        False,
        "Refresh the run before deciding whether another action is needed.",
    ),
    "GATE_DECISION_CONFLICT": ErrorDescriptor(
        "This approval gate was already decided by another request.",
        ErrorCategory.CONFLICT,
        False,
        "Refresh the run and use the recorded decision; do not submit it again.",
    ),
    "COMMAND_NOT_APPROVED": ErrorDescriptor(
        "The write command has not received the required approval.",
        ErrorCategory.POLICY,
        False,
        "Complete the current approval gate before executing the command.",
    ),
    "COMMAND_CAS_CONFLICT": ErrorDescriptor(
        "The write command changed while it was being executed.",
        ErrorCategory.CONFLICT,
        False,
        "Reconcile the command and target-system state before attempting another write.",
    ),
}


def error_descriptor(code: ErrorCode | str) -> ErrorDescriptor:
    value = code.value if isinstance(code, ErrorCode) else str(code)
    return _CATALOG.get(value, _DEFAULT)


def operational_error(
    code: ErrorCode | str,
    *,
    trace_id: str,
    details: dict[str, Any] | None = None,
) -> ErrorResponse:
    value = code.value if isinstance(code, ErrorCode) else str(code)
    descriptor = error_descriptor(value)
    return ErrorResponse(
        code=value,
        message=descriptor.message,
        trace_id=trace_id,
        category=descriptor.category,
        retryable=descriptor.retryable,
        operator_action=descriptor.operator_action,
        details=details or {},
    )
