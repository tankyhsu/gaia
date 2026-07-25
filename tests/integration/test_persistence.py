from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from gaia.contracts.models import (
    EventStatus,
    RunMode,
    RunSnapshot,
    RunStatus,
    UserIdentity,
    VersionBundle,
)
from gaia.persistence.models import Base, RunEventRecord, RunRecord
from gaia.runtime.dependencies import RuntimeDependencies, WriteToolRegistry
from gaia.runtime.ledger import RuntimeLedger
from gaia.runtime.persistent_engine import PersistentRuntimeEngine


@pytest.mark.asyncio
async def test_all_p0_tables_and_event_sequence_constraint(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/gaia.db"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        tables = await connection.run_sync(lambda sync: sync.dialect.get_table_names(sync))
    expected = {
        "runs",
        "run_events",
        "human_gates",
        "side_effect_commands",
        "idempotency_records",
        "artifacts",
        "replay_jobs",
        "replay_case_results",
    }
    assert expected <= set(tables)
    await engine.dispose()


@pytest.mark.asyncio
async def test_status_transition_and_event_commit_together(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/transition.db"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        session.add(
            RunRecord(
                run_id="run-transition",
                scenario_id="controlled-task",
                mode="mock",
                status="running",
                user_json={"id": "u", "organization": "org-alpha", "roles": ["reader"]},
                request_json={},
                version_bundle={},
                result_json=None,
                error_json=None,
                pending_gate_id=None,
                trace_id="t",
                created_at=now,
                updated_at=now,
            )
        )
    runtime = PersistentRuntimeEngine(
        factory,
        RuntimeDependencies(runners={}, write_tools=WriteToolRegistry()),
    )
    await runtime.transition(run_id="run-transition", status=RunStatus.SUCCEEDED, step="finalize")
    async with factory() as session:
        run = await session.get(RunRecord, "run-transition")
        events = (
            await session.scalars(
                select(RunEventRecord).where(RunEventRecord.run_id == "run-transition")
            )
        ).all()
        assert run is not None and run.status == "succeeded"
        assert len(events) == 1
    await engine.dispose()


def test_event_has_unique_run_sequence_constraint() -> None:
    constraints = RunEventRecord.__table__.constraints
    assert any(getattr(item, "name", None) == "uq_run_event_sequence" for item in constraints)


@pytest.mark.asyncio
async def test_runtime_ledger_persists_run_and_event_across_sessions(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/ledger.db"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    snapshot = RunSnapshot(
        run_id="run-1",
        scenario_id="controlled-task",
        mode=RunMode.MOCK,
        status=RunStatus.RECEIVED,
        user=UserIdentity(id="u", organization="org-alpha", roles=["reader"]),
        version_bundle=VersionBundle(
            policy="p",
            workflow="w",
            rules="r",
            prompt="p",
            model_profile="m",
            toolset="t",
            context_profile="c",
        ),
        created_at=now,
        updated_at=now,
    )
    async with factory.begin() as session:
        ledger = RuntimeLedger(session)
        await ledger.create_run(snapshot, {"text": "inspect"}, "trace")
        await ledger.event("run-1", "validate_request", EventStatus.SUCCEEDED)
    async with factory() as session:
        record = await RuntimeLedger(session).get_run("run-1")
        assert record is not None and record.status == "received"
    await engine.dispose()
