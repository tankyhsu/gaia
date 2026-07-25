"""Explicit, bounded agent handoffs for application-owned orchestration."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class AgentHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_agent: str
    input: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: dict[str, Any] | None = None
    handoff: AgentHandoff | None = None
    state_updates: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> AgentResult:
        if (self.output is None) == (self.handoff is None):
            raise ValueError("agent result requires exactly one of output or handoff")
        return self


@dataclass(frozen=True)
class AgentContext:
    run_id: str
    scenario_id: str
    agent_id: str
    input: Mapping[str, Any]
    shared_state: Mapping[str, Any]
    handoff_count: int


AgentHandler = Callable[[AgentContext], Awaitable[AgentResult]]


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    handler: AgentHandler
    allowed_handoffs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _AGENT_ID.fullmatch(self.agent_id) is None:
            raise ValueError("agent_id contains unsupported characters")
        if len(self.allowed_handoffs) != len(set(self.allowed_handoffs)):
            raise ValueError("allowed_handoffs must be unique")


class MultiAgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    target_agent: str | None = None
    reason: str | None = None


class MultiAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: dict[str, Any]
    final_agent: str
    handoff_count: int
    steps: tuple[MultiAgentStep, ...]
    shared_state: dict[str, Any]


class MultiAgentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HandoffOrchestrator:
    """Run allowlisted agent handoffs without an unbounded autonomous loop."""

    def __init__(self, agents: tuple[AgentSpec, ...], *, max_handoffs: int = 4) -> None:
        if not agents:
            raise ValueError("at least one agent is required")
        if max_handoffs < 0:
            raise ValueError("max_handoffs must be non-negative")
        self._agents = {agent.agent_id: agent for agent in agents}
        if len(self._agents) != len(agents):
            raise ValueError("agent_id must be unique")
        for agent in agents:
            unknown = set(agent.allowed_handoffs).difference(self._agents)
            if unknown:
                raise ValueError(f"unknown handoff targets for {agent.agent_id}: {sorted(unknown)}")
        self._max_handoffs = max_handoffs

    async def run(
        self,
        *,
        initial_agent: str,
        input: Mapping[str, Any],
        run_id: str = "unbound",
        scenario_id: str = "unbound",
        shared_state: Mapping[str, Any] | None = None,
    ) -> MultiAgentResult:
        if initial_agent not in self._agents:
            raise MultiAgentError("MULTI_AGENT_INITIAL_AGENT_NOT_FOUND")
        current_id = initial_agent
        current_input = dict(input)
        state = dict(shared_state or {})
        handoff_count = 0
        steps: list[MultiAgentStep] = []
        while True:
            agent = self._agents[current_id]
            result = await agent.handler(
                AgentContext(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    agent_id=current_id,
                    input=current_input,
                    shared_state=state,
                    handoff_count=handoff_count,
                )
            )
            state.update(result.state_updates)
            if result.output is not None:
                steps.append(MultiAgentStep(agent_id=current_id))
                return MultiAgentResult(
                    output=result.output,
                    final_agent=current_id,
                    handoff_count=handoff_count,
                    steps=tuple(steps),
                    shared_state=state,
                )
            handoff = result.handoff
            if handoff is None:
                raise MultiAgentError("MULTI_AGENT_INVALID_RESULT")
            if handoff.target_agent not in agent.allowed_handoffs:
                raise MultiAgentError("MULTI_AGENT_HANDOFF_NOT_ALLOWED")
            if handoff_count >= self._max_handoffs:
                raise MultiAgentError("MULTI_AGENT_BUDGET_EXCEEDED")
            steps.append(
                MultiAgentStep(
                    agent_id=current_id,
                    target_agent=handoff.target_agent,
                    reason=handoff.reason,
                )
            )
            handoff_count += 1
            current_id = handoff.target_agent
            current_input = dict(handoff.input)
