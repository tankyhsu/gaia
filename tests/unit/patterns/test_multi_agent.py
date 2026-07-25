from __future__ import annotations

import pytest

from gaia.patterns import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentSpec,
    HandoffOrchestrator,
    MultiAgentError,
)


async def test_allowlisted_handoff_returns_trace_and_shared_state() -> None:
    async def coordinator(context: AgentContext) -> AgentResult:
        return AgentResult(
            handoff=AgentHandoff(
                target_agent="specialist",
                input={"question": context.input["question"]},
                reason="specialist capability required",
            ),
            state_updates={"classified": True},
        )

    async def specialist(context: AgentContext) -> AgentResult:
        assert context.shared_state["classified"] is True
        return AgentResult(output={"answer": f"handled: {context.input['question']}"})

    orchestrator = HandoffOrchestrator(
        (
            AgentSpec("coordinator", coordinator, allowed_handoffs=("specialist",)),
            AgentSpec("specialist", specialist),
        )
    )

    result = await orchestrator.run(
        initial_agent="coordinator",
        input={"question": "status"},
        run_id="run-1",
        scenario_id="support",
    )

    assert result.output == {"answer": "handled: status"}
    assert result.final_agent == "specialist"
    assert result.handoff_count == 1
    assert result.steps[0].target_agent == "specialist"
    assert result.shared_state == {"classified": True}


async def test_handoff_route_must_be_allowlisted() -> None:
    async def agent(_: AgentContext) -> AgentResult:
        return AgentResult(handoff=AgentHandoff(target_agent="writer", reason="not permitted"))

    async def writer(_: AgentContext) -> AgentResult:
        return AgentResult(output={"ok": True})

    orchestrator = HandoffOrchestrator((AgentSpec("reader", agent), AgentSpec("writer", writer)))

    with pytest.raises(MultiAgentError, match="MULTI_AGENT_HANDOFF_NOT_ALLOWED"):
        await orchestrator.run(initial_agent="reader", input={})


async def test_handoff_budget_stops_cycles() -> None:
    async def to_b(_: AgentContext) -> AgentResult:
        return AgentResult(handoff=AgentHandoff(target_agent="b", reason="next"))

    async def to_a(_: AgentContext) -> AgentResult:
        return AgentResult(handoff=AgentHandoff(target_agent="a", reason="again"))

    orchestrator = HandoffOrchestrator(
        (
            AgentSpec("a", to_b, allowed_handoffs=("b",)),
            AgentSpec("b", to_a, allowed_handoffs=("a",)),
        ),
        max_handoffs=1,
    )

    with pytest.raises(MultiAgentError, match="MULTI_AGENT_BUDGET_EXCEEDED"):
        await orchestrator.run(initial_agent="a", input={})
