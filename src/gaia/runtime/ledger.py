"""SQLAlchemy-backed Runtime ledger for Run, Event, Gate, and Command ownership."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gaia.contracts.models import ActorType, EventStatus, RunEvent, RunSnapshot
from gaia.persistence.models import (
    HumanGateRecord,
    RunEventRecord,
    RunRecord,
    SideEffectCommandRecord,
)


class RuntimeLedger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_event(self, event: RunEvent) -> None:
        self._session.add(
            RunEventRecord(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                timestamp=event.timestamp,
                actor=event.actor.value,
                step=event.step,
                status=event.status.value,
                input_ref=event.input_ref,
                output_ref=event.output_ref,
                source_refs=event.source_refs,
                rule_refs=event.rule_refs,
                error_code=event.error_code,
                details=event.details,
            )
        )

    async def event(self, run_id: str, step: str, status: EventStatus) -> RunEvent:
        sequence = (
            await self._session.scalar(
                select(func.max(RunEventRecord.sequence)).where(RunEventRecord.run_id == run_id)
            )
            or 0
        ) + 1
        event = RunEvent(
            event_id=str(uuid4()),
            run_id=run_id,
            sequence=sequence,
            timestamp=datetime.now(UTC),
            actor=ActorType.SYSTEM,
            step=step,
            status=status,
            source_refs=[],
            rule_refs=[],
        )
        await self.append_event(event)
        return event

    async def create_run(
        self, snapshot: RunSnapshot, request_json: dict[str, object], trace_id: str
    ) -> None:
        self._session.add(
            RunRecord(
                run_id=snapshot.run_id,
                scenario_id=snapshot.scenario_id,
                mode=snapshot.mode.value,
                status=snapshot.status.value,
                user_json=snapshot.user.model_dump(mode="json"),
                request_json=request_json,
                version_bundle=snapshot.version_bundle.model_dump(),
                result_json=snapshot.result,
                error_json=snapshot.error.model_dump(mode="json") if snapshot.error else None,
                pending_gate_id=snapshot.pending_gate_id,
                trace_id=trace_id,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
        )

    async def get_run(self, run_id: str) -> RunRecord | None:
        return await self._session.get(RunRecord, run_id)

    async def add_gate(self, record: HumanGateRecord) -> None:
        self._session.add(record)

    async def add_command(self, record: SideEffectCommandRecord) -> None:
        self._session.add(record)
