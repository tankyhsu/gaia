"""Declarative scenario metadata with no runtime side effects."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from gaia.contracts.models import (
    ActorType,
    ErrorCode,
    ExecutionPolicy,
    RunRequest,
    RunStatus,
    VersionBundle,
    WriteMode,
)
from gaia.spi.model import ModelProvider
from gaia.spi.prompt import PromptRef
from gaia.spi.rag import Retriever
from gaia.spi.tool import ScenarioSideEffect, ScenarioTools

_SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SPEC_ATTRIBUTE = "__gaia_scenario_spec__"
_AGENT_HANDLER_ATTRIBUTE = "__gaia_agent_handler__"
_CONTINUATION_HANDLER_ATTRIBUTE = "__gaia_continuation_handler__"


@dataclass(frozen=True)
class ScenarioContext:
    """Inputs available to one application-owned scenario function."""

    run_id: str
    request: RunRequest
    tools: ScenarioTools | None = None
    model: ModelProvider | None = None
    retriever: Retriever | None = None
    agent_id: str | None = None
    handoff_input: Mapping[str, Any] = field(default_factory=dict)
    shared_state: Mapping[str, Any] = field(default_factory=dict)
    handoff_count: int = 0
    continuation_input: Mapping[str, Any] = field(default_factory=dict)
    action_result: Mapping[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.request.request.text

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self.request.request.metadata


@dataclass(frozen=True)
class ScenarioTrace:
    """Application evidence that Gaia persists in the common event stream."""

    name: str
    actor: ActorType = ActorType.SYSTEM
    source_refs: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioHandoff:
    """One explicit transfer to an application-registered Agent handler."""

    target_agent: str
    input: Mapping[str, Any]
    reason: str
    state_updates: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioContinuation:
    """A named application handler invoked after an action or action plan succeeds."""

    handler: str
    input: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.handler:
            raise ValueError("continuation handler must not be empty")


@dataclass(frozen=True)
class ScenarioResponse:
    """Explicit non-default result returned by a function scenario."""

    status: RunStatus
    result: Mapping[str, Any] | None = None
    pending_result: Mapping[str, Any] | None = None
    error_code: ErrorCode | str | None = None
    trace: tuple[ScenarioTrace, ...] = ()
    decision_step: str = "scenario"
    decision_rule_refs: tuple[str, ...] = ()
    side_effect: ScenarioSideEffect | None = None
    agent_handoff: ScenarioHandoff | None = None
    continuation: ScenarioContinuation | None = None

    def __post_init__(self) -> None:
        terminal = {
            RunStatus.SUCCEEDED,
            RunStatus.BLOCKED,
            RunStatus.DEGRADED,
            RunStatus.FAILED,
        }
        outcomes = sum(
            (
                self.side_effect is not None,
                self.agent_handoff is not None,
            )
        )
        if outcomes > 1:
            raise ValueError("use one of side_effect or agent_handoff")
        if outcomes == 0 and self.status not in terminal:
            raise ValueError("a scenario response without continuation must be terminal")
        if outcomes > 0 and self.status != RunStatus.RUNNING:
            raise ValueError("a scenario response with continuation must use running")
        if self.pending_result is not None and outcomes == 0:
            raise ValueError("pending_result requires a continuation")
        if self.continuation is not None and self.side_effect is None:
            raise ValueError("continuation requires a side effect")

    @classmethod
    def propose(
        cls,
        side_effect: ScenarioSideEffect,
        *,
        pending_result: Mapping[str, Any] | None = None,
        continue_with: str | None = None,
        continuation_input: Mapping[str, Any] | None = None,
        trace: tuple[ScenarioTrace, ...] = (),
        decision_step: str = "propose_side_effect",
        decision_rule_refs: tuple[str, ...] = (),
    ) -> ScenarioResponse:
        return cls(
            status=RunStatus.RUNNING,
            pending_result=pending_result,
            trace=trace,
            decision_step=decision_step,
            decision_rule_refs=decision_rule_refs,
            side_effect=side_effect,
            continuation=(
                None
                if continue_with is None
                else ScenarioContinuation(continue_with, continuation_input or {})
            ),
        )

    @classmethod
    def handoff_to(
        cls,
        target_agent: str,
        *,
        input: Mapping[str, Any],
        reason: str,
        state_updates: Mapping[str, Any] | None = None,
        pending_result: Mapping[str, Any] | None = None,
        trace: tuple[ScenarioTrace, ...] = (),
        decision_rule_refs: tuple[str, ...] = (),
    ) -> ScenarioResponse:
        return cls(
            status=RunStatus.RUNNING,
            pending_result=pending_result,
            trace=trace,
            decision_step="agent_handoff",
            decision_rule_refs=decision_rule_refs,
            agent_handoff=ScenarioHandoff(
                target_agent=target_agent,
                input=input,
                reason=reason,
                state_updates=state_updates or {},
            ),
        )


ScenarioValue = Mapping[str, Any] | BaseModel | ScenarioResponse
ScenarioHandler = Callable[[ScenarioContext], Awaitable[ScenarioValue]]


@dataclass(frozen=True)
class ScenarioSpec:
    """Immutable scenario declaration consumed by a runner adapter."""

    scenario_id: str
    title: str
    handler: ScenarioHandler
    version: str
    policy_id: str
    policy_version: str
    prompt_version: str
    prompt_ref: PromptRef | None
    model_profile: str
    rules_version: str
    toolset_version: str
    context_profile: str
    allowed_tools: tuple[str, ...]
    recognized_roles: tuple[str, ...]
    max_steps: int
    max_duration_seconds: int
    max_model_calls: int
    write_mode: WriteMode
    human_gate_rules: tuple[str, ...]
    uses_retrieval: bool
    allowed_handoffs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _SCENARIO_ID.fullmatch(self.scenario_id) is None:
            raise ValueError("scenario_id must match ^[a-z0-9][a-z0-9._-]{0,127}$")
        if not inspect.iscoroutinefunction(self.handler):
            raise TypeError("scenario handler must be async")
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("scenario allowed_tools must be unique")
        if not self.recognized_roles:
            raise ValueError("scenario recognized_roles must not be empty")
        if len(self.recognized_roles) != len(set(self.recognized_roles)):
            raise ValueError("scenario recognized_roles must be unique")
        if self.max_steps < 1 or self.max_duration_seconds < 1 or self.max_model_calls < 0:
            raise ValueError("scenario budgets are invalid")

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return ExecutionPolicy(
            policy_id=self.policy_id,
            version=self.policy_version,
            scenario_id=self.scenario_id,
            allowed_tools=list(self.allowed_tools),
            recognized_roles=list(self.recognized_roles),
            max_steps=self.max_steps,
            max_duration_seconds=self.max_duration_seconds,
            max_model_calls=self.max_model_calls,
            write_mode=self.write_mode,
            human_gate_rules=list(self.human_gate_rules),
        )

    @property
    def version_bundle(self) -> VersionBundle:
        prompt_version = self.prompt_version
        if self.prompt_ref is not None:
            selector = (
                self.prompt_ref.version or self.prompt_ref.environment or self.prompt_ref.experiment
            )
            prompt_version = f"{self.prompt_ref.prompt_id}:{selector}"
        return VersionBundle(
            policy=f"{self.policy_id}:{self.policy_version}",
            workflow=f"function:{self.version}",
            rules=self.rules_version,
            prompt=prompt_version,
            model_profile=self.model_profile,
            toolset=self.toolset_version,
            context_profile=self.context_profile,
        )


HandlerType = TypeVar("HandlerType", bound=ScenarioHandler)


def scenario(
    scenario_id: str,
    *,
    title: str | None = None,
    version: str = "1.0.0",
    policy_id: str | None = None,
    policy_version: str = "1.0.0",
    prompt_version: str = "unversioned",
    prompt: PromptRef | None = None,
    model_profile: str = "default",
    rules_version: str = "1.0.0",
    toolset_version: str = "1.0.0",
    context_profile: str = "default",
    allowed_tools: tuple[str, ...] = (),
    recognized_roles: tuple[str, ...] = ("user",),
    max_steps: int = 10,
    max_duration_seconds: int = 30,
    max_model_calls: int = 1,
    write_mode: WriteMode = WriteMode.DISABLED,
    human_gate_rules: tuple[str, ...] = (),
    uses_retrieval: bool = False,
    allowed_handoffs: tuple[str, ...] = (),
) -> Callable[[HandlerType], HandlerType]:
    """Attach immutable Gaia metadata while returning the original function."""

    def decorate(handler: HandlerType) -> HandlerType:
        spec = ScenarioSpec(
            scenario_id=scenario_id,
            title=title or scenario_id,
            handler=handler,
            version=version,
            policy_id=policy_id or f"policy-{scenario_id}",
            policy_version=policy_version,
            prompt_version=prompt_version,
            prompt_ref=prompt,
            model_profile=model_profile,
            rules_version=rules_version,
            toolset_version=toolset_version,
            context_profile=context_profile,
            allowed_tools=allowed_tools,
            recognized_roles=recognized_roles,
            max_steps=max_steps,
            max_duration_seconds=max_duration_seconds,
            max_model_calls=max_model_calls,
            write_mode=write_mode,
            human_gate_rules=human_gate_rules,
            uses_retrieval=uses_retrieval,
            allowed_handoffs=allowed_handoffs,
        )
        setattr(handler, _SPEC_ATTRIBUTE, spec)
        return handler

    return decorate


def get_scenario_spec(handler: ScenarioHandler) -> ScenarioSpec:
    """Return metadata from a decorated handler without using a global registry."""

    try:
        return cast(ScenarioSpec, getattr(handler, _SPEC_ATTRIBUTE))
    except AttributeError as error:
        raise ValueError("scenario handler is missing @scenario metadata") from error


@dataclass(frozen=True)
class AgentHandlerSpec:
    """Declares one Agent handoff target and its own outgoing routes.

    The runtime's `allowed_handoffs` routing table is assembled per-hop: the
    `"scenario"` entry comes from `@scenario(allowed_handoffs=...)`, and every other
    entry comes from the `@agent_handler` that owns that agent id. There is no implicit
    default edge -- an agent that does not declare `allowed_handoffs` can receive a
    handoff but cannot itself hand off to anything.
    """

    agent_id: str
    allowed_handoffs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must not be empty")


def agent_handler(
    agent_id: str,
    *,
    allowed_handoffs: tuple[str, ...] = (),
) -> Callable[[HandlerType], HandlerType]:
    """Attach immutable Agent-handoff-target metadata while returning the original function.

    Follows the same no-side-effects pattern as `@scenario`: the decorator only attaches
    an `AgentHandlerSpec`, it does not register the handler with any runtime.
    """

    def decorate(handler: HandlerType) -> HandlerType:
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("agent handler must be async")
        spec = AgentHandlerSpec(agent_id=agent_id, allowed_handoffs=allowed_handoffs)
        setattr(handler, _AGENT_HANDLER_ATTRIBUTE, spec)
        return cast(HandlerType, handler)

    return decorate


def get_agent_handler_spec(handler: ScenarioHandler) -> AgentHandlerSpec:
    """Return `@agent_handler` metadata from a decorated handler."""

    try:
        return cast(AgentHandlerSpec, getattr(handler, _AGENT_HANDLER_ATTRIBUTE))
    except AttributeError as error:
        raise ValueError("handler is missing @agent_handler metadata") from error


def continuation_handler(name: str) -> Callable[[HandlerType], HandlerType]:
    """Attach an immutable continuation name while returning the original function.

    Follows the same no-side-effects pattern as `@scenario`: the decorator only attaches
    the continuation name, it does not register the handler with any runtime.
    """

    if not name:
        raise ValueError("continuation handler name must not be empty")

    def decorate(handler: HandlerType) -> HandlerType:
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("continuation handler must be async")
        setattr(handler, _CONTINUATION_HANDLER_ATTRIBUTE, name)
        return cast(HandlerType, handler)

    return decorate


def get_continuation_handler_name(handler: ScenarioHandler) -> str:
    """Return `@continuation_handler` metadata from a decorated handler."""

    try:
        return cast(str, getattr(handler, _CONTINUATION_HANDLER_ATTRIBUTE))
    except AttributeError as error:
        raise ValueError("handler is missing @continuation_handler metadata") from error
