"""Focused repositories; no update or delete methods exist for events."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gaia.persistence.models import (
    HumanGateRecord,
    IdempotencyRecord,
    RunEventRecord,
    RunRecord,
    SideEffectCommandRecord,
)


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: RunRecord) -> None:
        self._session.add(record)

    async def get(self, run_id: str) -> RunRecord | None:
        return await self._session.get(RunRecord, run_id)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, record: RunEventRecord) -> None:
        self._session.add(record)

    async def list_after(self, run_id: str, sequence: int) -> list[RunEventRecord]:
        result = await self._session.scalars(
            select(RunEventRecord)
            .where(RunEventRecord.run_id == run_id, RunEventRecord.sequence > sequence)
            .order_by(RunEventRecord.sequence)
        )
        return list(result)


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        record = await self._session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.key == key
            )
        )
        return record

    async def add(self, record: IdempotencyRecord) -> None:
        self._session.add(record)


class GateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: HumanGateRecord) -> None:
        self._session.add(record)

    async def get(self, gate_id: str) -> HumanGateRecord | None:
        return await self._session.get(HumanGateRecord, gate_id)


class CommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: SideEffectCommandRecord) -> None:
        self._session.add(record)

    async def get(self, command_id: str) -> SideEffectCommandRecord | None:
        return await self._session.get(SideEffectCommandRecord, command_id)

    async def list_recoverable(self) -> list[SideEffectCommandRecord]:
        result = await self._session.scalars(
            select(SideEffectCommandRecord).where(
                SideEffectCommandRecord.status.in_(["executing", "unknown"])
            )
        )
        return list(result)
