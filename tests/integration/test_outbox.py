from __future__ import annotations

from sqlalchemy import func, select

from gaia.capabilities.outbox import DEAD_LETTER, OutboxDispatcher, SqlAlchemyOutboxStore
from gaia.integrations.events import InProcessEventPublisher
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.persistence.models import OutboxEventRecord
from gaia.spi.events import EventEnvelope


async def test_outbox_commit_dispatch_and_business_rollback_share_transaction(tmp_path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/outbox.db")
    store = SqlAlchemyOutboxStore(factory)
    delivered: list[EventEnvelope] = []
    publisher = InProcessEventPublisher()

    async def capture(event: EventEnvelope) -> None:
        delivered.append(event)

    publisher.subscribe("run.events", capture)
    committed = EventEnvelope(
        topic="run.events",
        event_type="run.completed",
        key="run-1",
        payload={"status": "succeeded"},
    )
    rolled_back = EventEnvelope(
        topic="run.events",
        event_type="run.completed",
        key="run-2",
        payload={"status": "succeeded"},
    )
    try:
        async with factory.begin() as session:
            await store.enqueue(session, committed)
        async with factory() as session:
            transaction = await session.begin()
            await store.enqueue(session, rolled_back)
            await transaction.rollback()

        dispatcher = OutboxDispatcher(
            store,
            publisher,
            worker_id="worker-1",
            retry_delay_seconds=0,
        )
        report = await dispatcher.dispatch_once()
        empty = await dispatcher.dispatch_once()

        assert report.claimed == report.published == 1
        assert report.failed == report.dead_lettered == 0
        assert empty.claimed == 0
        assert [event.event_id for event in delivered] == [committed.event_id]
        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))
        assert count == 1
    finally:
        await dispose_session_factory(factory)


async def test_outbox_retries_then_dead_letters_failed_in_process_delivery(tmp_path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/dead-letter.db")
    store = SqlAlchemyOutboxStore(factory)
    publisher = InProcessEventPublisher()

    async def fail(event: EventEnvelope) -> None:
        del event
        raise RuntimeError("consumer unavailable")

    publisher.subscribe("model.events", fail)
    event = EventEnvelope(
        topic="model.events",
        event_type="model.failed",
        payload={"provider": "example"},
    )
    try:
        async with factory.begin() as session:
            await store.enqueue(session, event)
        dispatcher = OutboxDispatcher(
            store,
            publisher,
            worker_id="worker-1",
            max_attempts=2,
            retry_delay_seconds=0,
        )

        first = await dispatcher.dispatch_once()
        second = await dispatcher.dispatch_once()

        assert (first.failed, first.dead_lettered) == (1, 0)
        assert (second.failed, second.dead_lettered) == (1, 1)
        async with factory() as session:
            record = await session.get(OutboxEventRecord, event.event_id)
        assert record is not None
        assert record.status == DEAD_LETTER
        assert record.attempts == 2
        assert record.last_error == "RuntimeError: consumer unavailable"
    finally:
        await dispose_session_factory(factory)


async def test_outbox_lease_prevents_a_second_worker_from_claiming_same_event(tmp_path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/lease.db")
    store = SqlAlchemyOutboxStore(factory)
    event = EventEnvelope(topic="run.events", event_type="run.created", payload={})
    try:
        async with factory.begin() as session:
            await store.enqueue(session, event)

        first = await store.claim_batch(worker_id="worker-1", batch_size=1, lease_seconds=30)
        second = await store.claim_batch(worker_id="worker-2", batch_size=1, lease_seconds=30)

        assert [claim.event.event_id for claim in first] == [event.event_id]
        assert second == ()
    finally:
        await dispose_session_factory(factory)
