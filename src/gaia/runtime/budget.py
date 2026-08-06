"""Durable, concurrency-safe execution budgets for one Run."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from gaia.contracts.models import ExecutionPolicy, ModelEndpointProfile, ModelHealth
from gaia.spi.model import (
    ModelCallContext,
    ModelMessage,
    ModelProvider,
    ModelResult,
    ModelStreamChunk,
)


class BudgetKind(StrEnum):
    STEP = "step"
    MODEL_CALL = "model_call"
    DURATION = "duration"


class BudgetExceeded(ValueError):
    def __init__(self, kind: BudgetKind) -> None:
        super().__init__(f"{kind.value} budget exceeded")
        self.kind = kind


class RunBudgetStore(Protocol):
    async def reserve_step(
        self,
        run_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None: ...

    async def reserve_model_call(
        self,
        run_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None: ...

    async def assert_duration(self, run_id: str) -> None: ...

    async def enter_human_wait(
        self,
        run_id: str,
        *,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> None: ...

    async def leave_human_wait(
        self,
        run_id: str,
        *,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> None: ...


@dataclass
class _TemporalBudgetState:
    run_id: str
    max_steps: int
    max_model_calls: int
    max_duration_seconds: int
    steps_used: int = 0
    model_calls_used: int = 0
    on_change: Callable[[dict[str, int]], None] | None = None

    def snapshot(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_model_calls": self.max_model_calls,
            "max_duration_seconds": self.max_duration_seconds,
            "steps_used": self.steps_used,
            "model_calls_used": self.model_calls_used,
        }


class TemporalRunBudgetStore:
    """Activity-local counters durably carried by Temporal Workflow History.

    A Worker activates the store from the budget payload before invoking a
    runner. Every reservation heartbeats the updated counters, so an Activity
    retry cannot silently reset the model-call or step limit. Successful
    Activities return the same snapshot to the Workflow for the next handoff
    or continuation.
    """

    def __init__(self) -> None:
        self._current: ContextVar[_TemporalBudgetState | None] = ContextVar(
            "gaia_temporal_run_budget",
            default=None,
        )

    def activate(
        self,
        run_id: str,
        policy: ExecutionPolicy,
        prior: object = None,
        *,
        on_change: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        values = prior if isinstance(prior, dict) else {}
        self._current.set(
            _TemporalBudgetState(
                run_id=run_id,
                max_steps=policy.max_steps,
                max_model_calls=policy.max_model_calls,
                max_duration_seconds=policy.max_duration_seconds,
                steps_used=int(values.get("steps_used", 0)),
                model_calls_used=int(values.get("model_calls_used", 0)),
                on_change=on_change,
            )
        )

    def snapshot(self) -> dict[str, int]:
        return self._state().snapshot()

    async def reserve_step(
        self,
        run_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        del session
        state = self._state(run_id)
        if state.steps_used >= state.max_steps:
            raise BudgetExceeded(BudgetKind.STEP)
        state.steps_used += 1
        self._changed(state)

    async def reserve_model_call(
        self,
        run_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        del session
        state = self._state(run_id)
        if state.model_calls_used >= state.max_model_calls:
            raise BudgetExceeded(BudgetKind.MODEL_CALL)
        state.model_calls_used += 1
        self._changed(state)

    async def assert_duration(self, run_id: str) -> None:
        self._state(run_id)

    async def enter_human_wait(
        self,
        run_id: str,
        *,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        del at, session
        self._state(run_id)

    async def leave_human_wait(
        self,
        run_id: str,
        *,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        del at, session
        self._state(run_id)

    def _state(self, run_id: str | None = None) -> _TemporalBudgetState:
        state = self._current.get()
        if state is None:
            raise RuntimeError("Temporal Run budget is not active")
        if run_id is not None and state.run_id != run_id:
            raise RuntimeError("Temporal Run budget belongs to a different Run")
        return state

    @staticmethod
    def _changed(state: _TemporalBudgetState) -> None:
        if state.on_change is not None:
            state.on_change(state.snapshot())


class InProcessRunBudgetStore(TemporalRunBudgetStore):
    """Request-local budget counters for the lightweight Runtime provider.

    The counters use the same context-local semantics as Temporal activities,
    but are activated directly by ``InProcessRuntimeEngine`` and never depend
    on a Worker, heartbeat, or Workflow History.
    """


class BudgetedModelProvider:
    """Reserve the Workflow-carried model budget before provider invocation."""

    def __init__(self, provider: ModelProvider, budget: RunBudgetStore) -> None:
        self._provider = provider
        self._budget = budget

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        return await self._provider.health(profile)

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult:
        await self._reserve(context)
        return await self._provider.generate_structured(
            profile=profile,
            messages=messages,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            context=context,
        )

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        await self._reserve(context)
        async for chunk in self._provider.generate_stream(
            profile=profile,
            messages=messages,
            timeout_seconds=timeout_seconds,
            context=context,
        ):
            yield chunk

    async def _reserve(self, context: ModelCallContext | None) -> None:
        if context is None or context.run_id == "unbound":
            return
        await self._budget.reserve_model_call(context.run_id)


class RunBudget:
    """Pure in-memory reference used for isolated policy tests."""

    def __init__(self, policy: ExecutionPolicy, received_at: datetime) -> None:
        self._policy = policy
        self._received_at = received_at.astimezone(UTC)
        self._steps = 0
        self._model_calls = 0
        self._waiting_since: datetime | None = None
        self._waited = timedelta()

    def enter_step(self) -> None:
        self._steps += 1
        if self._steps > self._policy.max_steps:
            raise BudgetExceeded(BudgetKind.STEP)

    def record_model_call(self) -> None:
        self._model_calls += 1
        if self._model_calls > self._policy.max_model_calls:
            raise BudgetExceeded(BudgetKind.MODEL_CALL)

    def enter_human_wait(self, at: datetime) -> None:
        self._waiting_since = at.astimezone(UTC)

    def leave_human_wait(self, at: datetime) -> None:
        if self._waiting_since is not None:
            self._waited += at.astimezone(UTC) - self._waiting_since
            self._waiting_since = None

    def assert_duration(self, now: datetime) -> None:
        elapsed = now.astimezone(UTC) - self._received_at - self._waited
        if self._waiting_since is not None:
            elapsed -= now.astimezone(UTC) - self._waiting_since
        if elapsed.total_seconds() > self._policy.max_duration_seconds:
            raise BudgetExceeded(BudgetKind.DURATION)
