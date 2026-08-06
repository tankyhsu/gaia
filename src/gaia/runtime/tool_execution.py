"""Run-scoped read-tool execution with policy and payload-free evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from gaia._authoring.tool import get_tool_spec
from gaia.contracts.models import (
    ApprovalView,
    ErrorCode,
    ExecutionPolicy,
    RunMode,
    RunRequest,
    ToolKind,
    ToolResult,
)
from gaia.guardrails import GuardrailPipeline, GuardrailViolation
from gaia.observability.models import ToolInvocation, ToolInvocationStatus
from gaia.runtime.budget import BudgetExceeded, RunBudgetStore
from gaia.runtime.dependencies import ToolRegistry
from gaia.runtime.policy import PolicyDenied, validate_tool_allowed
from gaia.spi.guardrail import GuardrailContext, GuardrailStage
from gaia.spi.tool import ScenarioSideEffect, ToolReference

logger = logging.getLogger(__name__)


class ToolInvocationSink(Protocol):
    async def record(self, invocation: ToolInvocation) -> None: ...


class NullToolInvocationSink:
    async def record(self, invocation: ToolInvocation) -> None:
        del invocation


class ToolExecutionError(RuntimeError):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class ScopedToolExecutor:
    """Execute only read tools admitted for one Run and Scenario policy."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        run_id: str,
        request: RunRequest,
        policy: ExecutionPolicy,
        environment: RunMode,
        sink: ToolInvocationSink | None = None,
        input_guardrails: GuardrailPipeline | None = None,
        output_guardrails: GuardrailPipeline | None = None,
        guardrails: GuardrailPipeline | None = None,
        budget: RunBudgetStore | None = None,
    ) -> None:
        self._registry = registry
        self._run_id = run_id
        self._request = request
        self._policy = policy
        self._environment = environment
        self._sink = sink or NullToolInvocationSink()
        self._input_guardrails = input_guardrails or guardrails
        self._output_guardrails = output_guardrails or guardrails
        self._budget = budget

    async def call(self, tool: ToolReference, /, **payload: Any) -> ToolResult:
        name = _tool_name(tool)
        started_at = datetime.now(UTC)
        started = perf_counter()
        invocation_id = str(uuid4())
        definition = None
        status = ToolInvocationStatus.FAILED
        output_ref: str | None = None
        error_code: ErrorCode | None = None
        try:
            try:
                definition = self._registry.definition(name)
            except KeyError as error:
                raise ToolExecutionError(ErrorCode.TOOL_NOT_REGISTERED) from error
            if definition.kind != ToolKind.READ:
                raise ToolExecutionError(ErrorCode.TOOL_DEFINITION_MISMATCH)
            try:
                validate_tool_allowed(self._policy, name)
            except PolicyDenied as error:
                raise ToolExecutionError(ErrorCode.TOOL_NOT_ALLOWED) from error
            if self._environment not in definition.allowed_environments:
                raise ToolExecutionError(ErrorCode.TOOL_ENVIRONMENT_MISMATCH)
            if set(definition.required_roles).difference(self._request.user.roles):
                raise ToolExecutionError(ErrorCode.TOOL_ROLE_REQUIRED)
            if self._budget is not None:
                try:
                    await self._budget.reserve_step(self._run_id)
                except BudgetExceeded as error:
                    raise ToolExecutionError(ErrorCode.BUDGET_EXCEEDED) from error
            guarded_payload = await self._guard(payload, stage=GuardrailStage.TOOL_INPUT)
            adapter = self._registry.read(name)
            try:
                result = await asyncio.wait_for(
                    adapter.execute(guarded_payload),
                    timeout=definition.timeout_seconds,
                )
            except TimeoutError as error:
                raise ToolExecutionError(ErrorCode.TOOL_TIMEOUT) from error
            if not result.ok:
                result_code = result.error_code
                raise ToolExecutionError(
                    result_code
                    if isinstance(result_code, ErrorCode)
                    else ErrorCode(str(result_code))
                    if result_code is not None and result_code in ErrorCode._value2member_map_
                    else ErrorCode.TOOL_ADAPTER_ERROR
                )
            guarded_result = await self._guard(
                result.data,
                stage=GuardrailStage.TOOL_OUTPUT,
            )
            result = result.model_copy(update={"data": guarded_result})
            status = ToolInvocationStatus.SUCCEEDED
            output_ref = _digest(result.data)
            return result
        except GuardrailViolation as error:
            error_code = ErrorCode.GUARDRAIL_BLOCKED
            status = ToolInvocationStatus.BLOCKED
            raise ToolExecutionError(error_code) from error
        except ToolExecutionError as error:
            error_code = error.code
            status = (
                ToolInvocationStatus.TIMED_OUT
                if error.code == ErrorCode.TOOL_TIMEOUT
                else ToolInvocationStatus.BLOCKED
                if error.code
                in {
                    ErrorCode.TOOL_NOT_REGISTERED,
                    ErrorCode.TOOL_NOT_ALLOWED,
                    ErrorCode.TOOL_ENVIRONMENT_MISMATCH,
                    ErrorCode.TOOL_ROLE_REQUIRED,
                    ErrorCode.TOOL_DEFINITION_MISMATCH,
                    ErrorCode.GUARDRAIL_BLOCKED,
                    ErrorCode.BUDGET_EXCEEDED,
                }
                else ToolInvocationStatus.FAILED
            )
            raise
        except Exception as error:
            error_code = ErrorCode.TOOL_ADAPTER_ERROR
            status = ToolInvocationStatus.FAILED
            raise ToolExecutionError(error_code) from error
        finally:
            invocation = ToolInvocation(
                invocation_id=invocation_id,
                run_id=self._run_id,
                scenario_id=self._request.scenario_id,
                tool_name=name,
                tool_version=definition.version if definition is not None else "unregistered",
                status=status,
                input_ref=_digest(payload),
                output_ref=output_ref,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                error_code=error_code.value if error_code is not None else None,
            )
            try:
                await self._sink.record(invocation)
            except Exception as sink_error:
                logger.warning(
                    "gaia_tool_observation_sink_failed error_type=%s",
                    type(sink_error).__name__,
                )

    def propose(
        self,
        tool: ToolReference,
        /,
        *,
        step_id: str,
        payload: Mapping[str, Any],
        reason: str,
        depends_on: tuple[str, ...] = (),
        approval_view: ApprovalView | None = None,
        rule_refs: tuple[str, ...] = (),
        uncertainty_rule_refs: tuple[str, ...] = (),
    ) -> ScenarioSideEffect:
        """Validate and return a write proposal; never instantiate or call the adapter."""

        name = _tool_name(tool)
        try:
            definition = self._registry.definition(name)
        except KeyError as error:
            raise ToolExecutionError(ErrorCode.TOOL_NOT_REGISTERED) from error
        if definition.kind != ToolKind.WRITE:
            raise ToolExecutionError(ErrorCode.TOOL_DEFINITION_MISMATCH)
        try:
            validate_tool_allowed(self._policy, name)
        except PolicyDenied as error:
            raise ToolExecutionError(ErrorCode.TOOL_NOT_ALLOWED) from error
        if self._environment not in definition.allowed_environments:
            raise ToolExecutionError(ErrorCode.TOOL_ENVIRONMENT_MISMATCH)
        if set(definition.required_roles).difference(self._request.user.roles):
            raise ToolExecutionError(ErrorCode.TOOL_ROLE_REQUIRED)
        return ScenarioSideEffect(
            step_id=step_id,
            tool_name=name,
            payload=payload,
            reason=reason,
            risk_level=definition.risk_level,
            depends_on=depends_on,
            approval_view=approval_view,
            rule_refs=rule_refs,
            uncertainty_rule_refs=uncertainty_rule_refs,
        )

    async def _guard(
        self,
        value: dict[str, Any],
        *,
        stage: GuardrailStage,
    ) -> dict[str, Any]:
        pipeline = (
            self._input_guardrails
            if stage == GuardrailStage.TOOL_INPUT
            else self._output_guardrails
        )
        if pipeline is None:
            return dict(value)
        guarded = await pipeline.evaluate(
            json.dumps(
                value,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ),
            GuardrailContext(
                stage=stage,
                run_id=self._run_id,
                scenario_id=self._request.scenario_id,
                metadata={"tool_policy": self._policy.policy_id},
            ),
        )
        try:
            decoded = json.loads(guarded)
        except json.JSONDecodeError as error:
            raise ToolExecutionError(ErrorCode.TOOL_ADAPTER_ERROR) from error
        if not isinstance(decoded, dict):
            raise ToolExecutionError(ErrorCode.TOOL_ADAPTER_ERROR)
        return decoded


def _tool_name(tool: ToolReference) -> str:
    if isinstance(tool, str):
        return tool
    return get_tool_spec(tool).definition.name


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
