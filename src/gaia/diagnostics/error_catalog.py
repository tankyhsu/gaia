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
    ErrorCode.DURABLE_EXECUTION_REQUIRED.value: ErrorDescriptor(
        "This run needs durable orchestration that the in-process provider does not perform.",
        ErrorCategory.CONFIGURATION,
        False,
        "Select runtime.execution.provider=temporal for long-running workflows, human waits, "
        "critical writes, or recovery across process restarts.",
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
    ErrorCode.MODEL_OUTPUT_INVALID.value: ErrorDescriptor(
        "The model did not produce a valid structured result within the correction budget.",
        ErrorCategory.RUNTIME,
        False,
        "Inspect the output schema, validator decision, Prompt, and model-call budget.",
    ),
    ErrorCode.TOOL_TIMEOUT.value: ErrorDescriptor(
        "The external tool did not respond before the timeout.",
        ErrorCategory.EXTERNAL_DEPENDENCY,
        True,
        "Check tool health and latency before retrying.",
    ),
    ErrorCode.GUARDRAIL_BLOCKED.value: ErrorDescriptor(
        "A configured safety rule blocked this request or generated content.",
        ErrorCategory.POLICY,
        False,
        "Inspect the guardrail decision, then correct the request or scanner policy.",
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
    ErrorCode.GATE_NOT_PENDING.value: ErrorDescriptor(
        "This approval gate has already been decided, expired, or is unknown.",
        ErrorCategory.POLICY,
        False,
        "Re-read the gate before deciding; an earlier decision is never overwritten.",
    ),
    ErrorCode.GATE_DECISION_UNVERIFIED.value: ErrorDescriptor(
        "The write was gated on human approval that Gaia cannot verify.",
        ErrorCategory.POLICY,
        False,
        (
            "The Workflow reported an approval that Gaia's audit projection does "
            "not hold. Approve through the Gaia API; a decision sent straight to "
            "the Temporal namespace is not an authenticated approval. Treat an "
            "unexplained occurrence as a possible forged decision and review who "
            "can reach that namespace."
        ),
    ),
    ErrorCode.BUDGET_EXCEEDED.value: ErrorDescriptor(
        "The run exceeded its configured execution budget.",
        ErrorCategory.RUNTIME,
        False,
        "Inspect step, model-call, and duration limits before adjusting the policy.",
    ),
    ErrorCode.HANDOFF_NOT_ALLOWED.value: ErrorDescriptor(
        "The current Agent is not allowed to transfer work to the requested target.",
        ErrorCategory.POLICY,
        False,
        "Review the explicit Agent handoff allowlist.",
    ),
    ErrorCode.HANDOFF_TARGET_NOT_FOUND.value: ErrorDescriptor(
        "The requested Agent handoff target is not registered.",
        ErrorCategory.CONFIGURATION,
        False,
        "Register the target handler or correct the handoff target ID.",
    ),
    ErrorCode.CONTINUATION_HANDLER_NOT_FOUND.value: ErrorDescriptor(
        "The requested post-action continuation handler is not registered.",
        ErrorCategory.CONFIGURATION,
        False,
        "Register the continuation handler or correct the continue_with value.",
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
    ErrorCode.RUNTIME_ILLEGAL_TRANSITION.value: ErrorDescriptor(
        "The runtime attempted a state transition that is not on the allowed list.",
        ErrorCategory.INTERNAL,
        False,
        "This indicates a runtime defect. Use the trace ID to inspect the event log and "
        "report the offending transition.",
    ),
    ErrorCode.IDENTITY_MISMATCH.value: ErrorDescriptor(
        "The authenticated caller identity does not match RunRequest.user.",
        ErrorCategory.CONFLICT,
        False,
        "Submit RunRequest.user matching the identity resolved by the configured "
        "AuthnProvider, or omit fields the provider already establishes; the server "
        "will not silently substitute the authenticated identity for a conflicting "
        "claim.",
    ),
    ErrorCode.POLICY_OVERRIDE_INVALID.value: ErrorDescriptor(
        "A configured policy override would loosen a scenario's policy instead of "
        "tightening it.",
        ErrorCategory.CONFIGURATION,
        False,
        "Fix the runtime.policy_overrides entry so every field only tightens the "
        "scenario's baseline policy, then redeploy; overrides are rejected at "
        "application startup, not at request time.",
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
    "SCENARIO_MODULE_NOT_FOUND": ErrorDescriptor(
        "A module listed under scenarios.modules could not be imported.",
        ErrorCategory.CONFIGURATION,
        False,
        "Install the project so its package is importable (e.g. `uv add --editable` / "
        "`pip install -e` your application, then `uv sync`), or correct the module path "
        "in scenarios.modules if it is simply misspelled.",
    ),
    "SCENARIO_MODULE_IMPORT_FAILED": ErrorDescriptor(
        "A module listed under scenarios.modules exists but raised an error while it was "
        "being imported.",
        ErrorCategory.CONFIGURATION,
        False,
        "Fix the module's own import-time code or install its missing dependency; the "
        "module path in scenarios.modules is correct and does not need to change.",
    ),
    "SCENARIO_DUPLICATE": ErrorDescriptor(
        "The same scenario_id is declared by more than one discovered scenario function.",
        ErrorCategory.CONFIGURATION,
        False,
        "Rename or remove the duplicate @scenario declaration so each scenario_id is unique "
        "across scenarios.modules.",
    ),
    "SCENARIO_TOOL_DUPLICATE": ErrorDescriptor(
        "The same tool name is declared by more than one discovered tool function.",
        ErrorCategory.CONFIGURATION,
        False,
        "Rename or remove the duplicate @read_tool or @write_tool declaration so each tool "
        "name is unique across scenarios.modules.",
    ),
    "AGENT_HANDLER_DUPLICATE": ErrorDescriptor(
        "The same agent_id is declared by more than one discovered @agent_handler function.",
        ErrorCategory.CONFIGURATION,
        False,
        "Rename or remove the duplicate @agent_handler declaration so each agent_id is "
        "unique across scenarios.modules.",
    ),
    "CONTINUATION_HANDLER_DUPLICATE": ErrorDescriptor(
        "The same continuation name is declared by more than one discovered "
        "@continuation_handler function.",
        ErrorCategory.CONFIGURATION,
        False,
        "Rename or remove the duplicate @continuation_handler declaration so each name is "
        "unique across scenarios.modules.",
    ),
    "APPLICATION_NOT_STARTED": ErrorDescriptor(
        "GaiaApplication.get_component was called before the application finished "
        "starting.",
        ErrorCategory.CONFIGURATION,
        False,
        "Call get_component only inside or after GaiaApplication.lifespan()/start() "
        "has completed, not during configure().",
    ),
    "COMPONENT_NOT_FOUND": ErrorDescriptor(
        "No component is registered under the requested component_id.",
        ErrorCategory.CONFIGURATION,
        False,
        "Check the component_id and confirm the Starter that registers it is active "
        "for the current profile and configuration.",
    ),
    "COMPONENT_TYPE_MISMATCH": ErrorDescriptor(
        "The component registered under this component_id does not satisfy the "
        "port type the caller required.",
        ErrorCategory.CONFIGURATION,
        False,
        "Check which Starter registered this component_id and correct the "
        "configuration so it provides the expected port implementation.",
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
