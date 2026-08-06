"""Transactional outbox capability built on Gaia's operational SQLAlchemy schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.persistence.models import OutboxEventRecord
from gaia.spi.events import EventEnvelope, EventPublisher

PENDING = "pending"
PUBLISHED = "published"
DEAD_LETTER = "dead_letter"


class OutboxLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboxClaim:
    event: EventEnvelope
    attempts: int


@dataclass(frozen=True)
class OutboxDispatchReport:
    claimed: int
    published: int
    failed: int
    dead_lettered: int


@dataclass(frozen=True)
class OutboxRuntimeFactory:
    """Configured capability factory bound to an application-owned session factory."""

    batch_size: int
    lease_seconds: int
    max_attempts: int
    retry_delay_seconds: int

    def store(
        self,
        factory: async_sessionmaker[AsyncSession],
    ) -> SqlAlchemyOutboxStore:
        return SqlAlchemyOutboxStore(factory)

    def dispatcher(
        self,
        factory: async_sessionmaker[AsyncSession],
        publisher: EventPublisher,
        *,
        worker_id: str,
    ) -> OutboxDispatcher:
        return OutboxDispatcher(
            self.store(factory),
            publisher,
            worker_id=worker_id,
            batch_size=self.batch_size,
            lease_seconds=self.lease_seconds,
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlAlchemyOutboxStore:
    """SQLAlchemy implementation; PostgreSQL provides concurrent SKIP LOCKED claims."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def enqueue(
        self,
        session: AsyncSession,
        event: EventEnvelope,
        *,
        available_at: datetime | None = None,
    ) -> None:
        now = _utcnow()
        session.add(
            OutboxEventRecord(
                event_id=event.event_id,
                topic=event.topic,
                event_type=event.event_type,
                event_key=event.key,
                payload_json=event.payload,
                headers_json=event.headers,
                status=PENDING,
                attempts=0,
                occurred_at=event.occurred_at,
                available_at=available_at or now,
                locked_by=None,
                locked_until=None,
                last_error=None,
                created_at=now,
                published_at=None,
            )
        )
        await session.flush()

    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> tuple[OutboxClaim, ...]:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if batch_size < 1 or lease_seconds < 1:
            raise ValueError("batch_size and lease_seconds must be positive")
        now = _utcnow()
        async with self._factory.begin() as session:
            statement = (
                select(OutboxEventRecord)
                .where(
                    OutboxEventRecord.status == PENDING,
                    OutboxEventRecord.available_at <= now,
                    or_(
                        OutboxEventRecord.locked_until.is_(None),
                        OutboxEventRecord.locked_until < now,
                    ),
                )
                .order_by(OutboxEventRecord.created_at, OutboxEventRecord.event_id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            records = list((await session.scalars(statement)).all())
            claims: list[OutboxClaim] = []
            for record in records:
                record.locked_by = worker_id
                record.locked_until = now + timedelta(seconds=lease_seconds)
                record.attempts += 1
                claims.append(
                    OutboxClaim(
                        event=EventEnvelope(
                            event_id=record.event_id,
                            topic=record.topic,
                            event_type=record.event_type,
                            key=record.event_key,
                            payload=record.payload_json,
                            headers=record.headers_json,
                            occurred_at=_aware(record.occurred_at),
                        ),
                        attempts=record.attempts,
                    )
                )
            return tuple(claims)

    async def mark_published(self, event_id: str, *, worker_id: str) -> None:
        async with self._factory.begin() as session:
            record = await self._locked_record(session, event_id, worker_id)
            record.status = PUBLISHED
            record.published_at = _utcnow()
            record.locked_by = None
            record.locked_until = None
            record.last_error = None

    async def mark_failed(
        self,
        event_id: str,
        *,
        worker_id: str,
        error: str,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> bool:
        if max_attempts < 1 or retry_delay_seconds < 0:
            raise ValueError("invalid retry policy")
        async with self._factory.begin() as session:
            record = await self._locked_record(session, event_id, worker_id)
            dead_lettered = record.attempts >= max_attempts
            record.status = DEAD_LETTER if dead_lettered else PENDING
            record.available_at = _utcnow() + timedelta(seconds=retry_delay_seconds)
            record.locked_by = None
            record.locked_until = None
            record.last_error = error[:2000]
            return dead_lettered

    async def _locked_record(
        self,
        session: AsyncSession,
        event_id: str,
        worker_id: str,
    ) -> OutboxEventRecord:
        record = await session.scalar(
            select(OutboxEventRecord)
            .where(
                OutboxEventRecord.event_id == event_id,
                OutboxEventRecord.status == PENDING,
                OutboxEventRecord.locked_by == worker_id,
            )
            .with_for_update()
        )
        if record is None:
            raise OutboxLeaseLost(event_id)
        return record


class OutboxDispatcher:
    def __init__(
        self,
        store: SqlAlchemyOutboxStore,
        publisher: EventPublisher,
        *,
        worker_id: str,
        batch_size: int = 50,
        lease_seconds: int = 30,
        max_attempts: int = 8,
        retry_delay_seconds: int = 5,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds

    async def dispatch_once(self) -> OutboxDispatchReport:
        claims = await self._store.claim_batch(
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        published = 0
        failed = 0
        dead_lettered = 0
        for claim in claims:
            try:
                await self._publisher.publish(claim.event)
            except Exception as error:
                failed += 1
                if await self._store.mark_failed(
                    claim.event.event_id,
                    worker_id=self._worker_id,
                    error=f"{type(error).__name__}: {error}",
                    max_attempts=self._max_attempts,
                    retry_delay_seconds=self._retry_delay_seconds,
                ):
                    dead_lettered += 1
            else:
                await self._store.mark_published(
                    claim.event.event_id,
                    worker_id=self._worker_id,
                )
                published += 1
        return OutboxDispatchReport(
            claimed=len(claims),
            published=published,
            failed=failed,
            dead_lettered=dead_lettered,
        )
