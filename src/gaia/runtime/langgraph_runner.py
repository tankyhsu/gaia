"""LangGraph logic adapter for Gaia's selectable execution providers.

The graph computes one logical step at a time. If that step proposes a write,
the graph state is carried in a RuntimeContinuation. Temporal records that
continuation in Workflow History; in-process execution expects an application-owned
LangGraph checkpointer and rejects continuations that require orchestration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from gaia.contracts.models import ExecutionPolicy, RunRequest, VersionBundle
from gaia.runtime.dependencies import (
    RuntimeContinuation,
    RuntimeHandoff,
    RuntimeOutcome,
)

LANGGRAPH_CONTINUATION = "__gaia_langgraph_next__"


class AsyncLangGraph(Protocol):
    """The narrow CompiledStateGraph port Gaia needs."""

    async def ainvoke(self, input: Mapping[str, Any]) -> Mapping[str, Any]: ...


GraphStateFactory = Callable[[str, RunRequest], Mapping[str, Any]]
GraphOutcomeMapper = Callable[[Mapping[str, Any]], RuntimeOutcome]


def _durable_state(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached JSON value suitable for Temporal payload history."""

    try:
        restored = json.loads(json.dumps(dict(value)))
    except (TypeError, ValueError) as error:
        raise ValueError("LangGraph state must be JSON serializable") from error
    if not isinstance(restored, dict):
        raise ValueError("LangGraph state must serialize to an object")
    return restored


class LangGraphScenarioRunner:
    """Adapt a LangGraph state machine to Gaia's one-outcome Runtime SPI.

    LangGraph owns logical routing. Temporal owns the durable loop, retries,
    HumanGate wait, and Command execution. The mapper must expose at most one
    side effect for each graph invocation.
    """

    def __init__(
        self,
        *,
        graph: AsyncLangGraph,
        execution_policy: ExecutionPolicy,
        version_bundle: VersionBundle,
        initial_state: GraphStateFactory,
        outcome_from_state: GraphOutcomeMapper,
        action_result_key: str = "action_result",
    ) -> None:
        if not action_result_key:
            raise ValueError("action_result_key must not be empty")
        self._graph = graph
        self._execution_policy = execution_policy
        self._version_bundle = version_bundle
        self._initial_state = initial_state
        self._outcome_from_state = outcome_from_state
        self._action_result_key = action_result_key

    @property
    def version_bundle(self) -> VersionBundle:
        return self._version_bundle

    @property
    def execution_policy(self) -> ExecutionPolicy:
        return self._execution_policy

    async def run(self, *, run_id: str, request: RunRequest) -> RuntimeOutcome:
        return await self._invoke(
            _durable_state(self._initial_state(run_id, request)),
        )

    async def run_continuation(
        self,
        *,
        run_id: str,
        request: RunRequest,
        continuation: RuntimeContinuation,
    ) -> RuntimeOutcome:
        del run_id, request
        if continuation.handler != LANGGRAPH_CONTINUATION:
            raise ValueError(
                f"unknown LangGraph continuation handler {continuation.handler!r}"
            )
        state = continuation.input.get("state")
        if not isinstance(state, Mapping):
            raise ValueError("LangGraph continuation requires object state")
        resumed = _durable_state(state)
        resumed[self._action_result_key] = _durable_state(continuation.action_result)
        return await self._invoke(resumed)

    async def _invoke(self, state: Mapping[str, Any]) -> RuntimeOutcome:
        graph_state = _durable_state(await self._graph.ainvoke(state))
        outcome = self._outcome_from_state(graph_state)
        if outcome.side_effect is None or outcome.continuation is not None:
            return outcome
        return replace(
            outcome,
            continuation=RuntimeContinuation(
                handler=LANGGRAPH_CONTINUATION,
                input={"state": graph_state},
            ),
        )

    async def run_handoff(
        self,
        *,
        run_id: str,
        request: RunRequest,
        handoff: RuntimeHandoff,
    ) -> RuntimeOutcome:
        del run_id, request, handoff
        raise ValueError("model agent routing as LangGraph edges, not Gaia handoffs")

    def bind_gate(self, *, run_id: str, gate_id: str) -> None:
        del run_id, gate_id

    def resume(self, *, run_id: str, decision: str) -> None:
        del run_id, decision
