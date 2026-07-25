"""Declarative scenario metadata with no runtime side effects."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from gaia.contracts.models import (
    ActorType,
    ErrorCode,
    ExecutionPolicy,
    RiskLevel,
    RunRequest,
    RunStatus,
    VersionBundle,
    WriteMode,
)
from gaia.sdk.prompt import PromptRef

_SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SPEC_ATTRIBUTE = "__gaia_scenario_spec__"


@dataclass(frozen=True)
class ScenarioContext:
    """Inputs available to one application-owned scenario function."""

    run_id: str
    request: RunRequest

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
class ScenarioSideEffect:
    """A requested write that the Gaia Runtime must authorize and execute."""

    step_id: str
    tool_name: str
    payload: Mapping[str, Any]
    reason: str
    risk_level: RiskLevel
    rule_refs: tuple[str, ...] = ()
    uncertainty_rule_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioResponse:
    """Explicit non-default result returned by a function scenario."""

    status: RunStatus
    result: Mapping[str, Any] | None = None
    error_code: ErrorCode | str | None = None
    trace: tuple[ScenarioTrace, ...] = ()
    decision_step: str = "scenario"
    decision_rule_refs: tuple[str, ...] = ()
    side_effect: ScenarioSideEffect | None = None

    def __post_init__(self) -> None:
        terminal = {
            RunStatus.SUCCEEDED,
            RunStatus.BLOCKED,
            RunStatus.DEGRADED,
            RunStatus.FAILED,
        }
        if self.side_effect is None and self.status not in terminal:
            raise ValueError("a scenario response without a side effect must be terminal")
        if self.side_effect is not None and self.status != RunStatus.RUNNING:
            raise ValueError("a scenario response with a side effect must use running")

    @classmethod
    def propose(
        cls,
        side_effect: ScenarioSideEffect,
        *,
        trace: tuple[ScenarioTrace, ...] = (),
        decision_step: str = "propose_side_effect",
        decision_rule_refs: tuple[str, ...] = (),
    ) -> ScenarioResponse:
        return cls(
            status=RunStatus.RUNNING,
            trace=trace,
            decision_step=decision_step,
            decision_rule_refs=decision_rule_refs,
            side_effect=side_effect,
        )


ScenarioValue = Mapping[str, Any] | BaseModel | ScenarioResponse
ScenarioHandler = Callable[[ScenarioContext], Awaitable[ScenarioValue]]


@dataclass(frozen=True)
class ScenarioSpec:
    """Immutable scenario declaration consumed by a runner adapter."""

    scenario_id: str
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
) -> Callable[[HandlerType], HandlerType]:
    """Attach immutable Gaia metadata while returning the original function."""

    def decorate(handler: HandlerType) -> HandlerType:
        spec = ScenarioSpec(
            scenario_id=scenario_id,
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
