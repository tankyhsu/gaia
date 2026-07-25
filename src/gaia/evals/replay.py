"""Application-neutral acceptance replay service."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.contracts.models import (
    HumanGateDecisionRequest,
    ReplayCaseResult,
    ReplayRequest,
    ReplaySnapshot,
    RunRequest,
    RunStatus,
)
from gaia.persistence.models import ReplayCaseResultRecord, ReplayJobRecord
from gaia.runtime.engine import RuntimeEngine


class ReplayFixtureSource(Protocol):
    def cases(self) -> list[dict[str, Any]]: ...

    def request_for(self, case: dict[str, Any]) -> RunRequest: ...


class ReplayRuntimeFixture(Protocol):
    def create_runtime(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> RuntimeEngine: ...


class JsonReplayFixtureSource:
    """Machine-readable fixture source shared by examples and applications."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._path.read_text(encoding="utf-8")))

    def cases(self) -> list[dict[str, Any]]:
        return list(self._payload()["cases"])

    def request_for(self, case: dict[str, Any]) -> RunRequest:
        payload = self._payload()
        return RunRequest.model_validate(
            {
                "scenario_id": payload["scenario_id"],
                "mode": payload.get("mode", "mock"),
                "user": case["user"],
                "request": {
                    "text": case["request_text"],
                    "metadata": case.get("setup", {}),
                },
            }
        )


class ReplayRunner:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        fixture_source: ReplayFixtureSource,
        runtime_fixture_factory: Callable[[], ReplayRuntimeFixture],
    ) -> None:
        self._factory = factory
        self._fixture_source = fixture_source
        self._runtime_fixture_factory = runtime_fixture_factory

    async def run(self, request: ReplayRequest) -> ReplaySnapshot:
        available = {case["case_id"]: case for case in self._fixture_source.cases()}
        selected_ids = list(available) if request.all else request.case_ids or []
        missing = [case_id for case_id in selected_ids if case_id not in available]
        if missing:
            raise ValueError(f"UNKNOWN_REPLAY_CASES:{','.join(missing)}")

        replay_id = str(uuid4())
        created_at = datetime.now(UTC)
        async with self._factory.begin() as session:
            session.add(
                ReplayJobRecord(
                    replay_id=replay_id,
                    status="running",
                    total=len(selected_ids),
                    passed=0,
                    failed=0,
                    created_at=created_at,
                    finished_at=None,
                )
            )

        results = [await self._run_case(replay_id, available[case_id]) for case_id in selected_ids]
        passed = sum(item.passed for item in results)
        finished_at = datetime.now(UTC)
        async with self._factory.begin() as session:
            job = await session.get(ReplayJobRecord, replay_id, with_for_update=True)
            if job is None:  # pragma: no cover - protected by the preceding transaction
                raise RuntimeError("replay job disappeared")
            job.status = "completed"
            job.passed = passed
            job.failed = len(results) - passed
            job.finished_at = finished_at
            session.add_all(
                [
                    ReplayCaseResultRecord(
                        replay_id=replay_id,
                        case_id=item.case_id,
                        passed=item.passed,
                        expected_status=item.expected_status.value,
                        actual_status=item.actual_status.value,
                        assertions=item.assertions,
                    )
                    for item in results
                ]
            )
        return ReplaySnapshot(
            replay_id=replay_id,
            status="completed",
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
            created_at=created_at,
            finished_at=finished_at,
        )

    async def get(self, replay_id: str) -> ReplaySnapshot:
        async with self._factory() as session:
            job = await session.get(ReplayJobRecord, replay_id)
            if job is None:
                raise KeyError(replay_id)
            rows = await session.scalars(
                select(ReplayCaseResultRecord)
                .where(ReplayCaseResultRecord.replay_id == replay_id)
                .order_by(ReplayCaseResultRecord.id)
            )
            results = [
                ReplayCaseResult(
                    case_id=row.case_id,
                    passed=row.passed,
                    expected_status=RunStatus(row.expected_status),
                    actual_status=RunStatus(row.actual_status),
                    assertions=row.assertions,
                )
                for row in rows
            ]
            return ReplaySnapshot(
                replay_id=job.replay_id,
                status=cast(Literal["running", "completed", "failed"], job.status),
                total=job.total,
                passed=job.passed,
                failed=job.failed,
                results=results,
                created_at=_aware(job.created_at),
                finished_at=_aware(job.finished_at) if job.finished_at else None,
            )

    async def _run_case(self, replay_id: str, case: dict[str, Any]) -> ReplayCaseResult:
        runtime_fixture = self._runtime_fixture_factory()
        runtime = runtime_fixture.create_runtime(self._factory)
        request = self._fixture_source.request_for(case)
        snapshot = await runtime.create(request, f"replay:{replay_id}:{case['idempotency_key']}")
        initial_run_id = snapshot.run_id
        for action in case.get("actions", []):
            action_type = action["type"]
            if action_type == "restart_runtime":
                runtime = runtime_fixture.create_runtime(self._factory)
            elif action_type == "human_decision":
                snapshot = await runtime.decide(
                    snapshot.pending_gate_id or "",
                    HumanGateDecisionRequest.model_validate(
                        {key: value for key, value in action.items() if key != "type"}
                    ),
                )
            elif action_type == "repeat_create_request":
                for _ in range(action["count"]):
                    snapshot = await runtime.create(
                        request, f"replay:{replay_id}:{case['idempotency_key']}"
                    )

        expected = case["expected"]
        events = await runtime.events_after(snapshot.run_id)
        steps = {event.step for event in events}
        rules = {rule for event in events for rule in event.rule_refs}
        actual_error = str(snapshot.error.code) if snapshot.error else None
        expected_result = expected["result_contains"]
        result_matches = not expected_result or (
            snapshot.result is not None
            and all(snapshot.result.get(key) == value for key, value in expected_result.items())
        )
        checks = {
            "status": snapshot.status.value == expected["status"],
            "error_code": actual_error == expected["error_code"],
            "result_contains": result_matches,
            "required_steps": set(expected["required_steps"]) <= steps,
            "forbidden_steps": not set(expected["forbidden_steps"]).intersection(steps),
            "required_rule_refs": set(expected["required_rule_refs"]) <= rules,
            "side_effect_success_count": runtime.side_effect_success_count
            == expected["side_effect_success_count"],
            "same_run_id": snapshot.run_id == initial_run_id,
        }
        assertions = [{"name": name, "passed": passed} for name, passed in checks.items()]
        return ReplayCaseResult(
            case_id=case["case_id"],
            passed=all(checks.values()),
            expected_status=RunStatus(expected["status"]),
            actual_status=snapshot.status,
            assertions=assertions,
        )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
