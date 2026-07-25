import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from examples.controlled_task import create_controlled_task_composition
from examples.controlled_task.read_tool import DEFAULT_RESOURCES
from examples.controlled_task.write_tool import MockResourceWriteAdapter
from gaia.contracts.models import HumanGateDecisionRequest, RunRequest, ToolResult
from gaia.persistence.database import initialize_database
from gaia.persistence.models import HumanGateRecord, RunRecord, SideEffectCommandRecord
from gaia.runtime.recovery import recover_runtime


def request() -> RunRequest:
    return RunRequest.model_validate(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {"id": "operator", "organization": "org-alpha", "roles": ["operator"]},
            "request": {"text": "pause res-001 because test"},
        }
    )


async def test_concurrent_create_same_key_returns_one_run(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/concurrent.db")
    first = create_controlled_task_composition().create_runtime(factory)
    second = create_controlled_task_composition().create_runtime(factory)
    results = await asyncio.gather(
        first.create(request(), "same-idempotency-key"),
        second.create(request(), "same-idempotency-key"),
    )
    assert results[0].run_id == results[1].run_id


async def test_repeated_recovery_reconciles_before_write(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/recovery.db")
    runtime = create_controlled_task_composition().create_runtime(factory)
    waiting = await runtime.create(request(), "recovery-key")
    restarted = create_controlled_task_composition().create_runtime(factory)
    assert waiting.run_id in await recover_runtime(restarted)
    result = await restarted.decide(
        waiting.pending_gate_id or "",
        HumanGateDecisionRequest(
            decision="approved", decided_by="approver", roles=["approver"], comment="ok"
        ),
    )
    assert result.status.value == "succeeded"
    final_runtime = create_controlled_task_composition().create_runtime(factory)
    assert (await recover_runtime(final_runtime)) == []


async def test_crash_at_executing_recovery_reconciles_without_replay(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/crash.db")
    first = create_controlled_task_composition().create_runtime(factory)
    waiting = await first.create(request(), "crash-key")
    command_id = (await first.get_gate(waiting.pending_gate_id or "")).command_id
    async with factory.begin() as session:
        command = await session.get(SideEffectCommandRecord, command_id)
        assert command is not None
        command.status = "executing"
    restarted = create_controlled_task_composition().create_runtime(factory)
    assert await recover_runtime(restarted) == []
    command = await restarted.get_command(command_id)
    assert command["status"] == "unknown"
    assert restarted.side_effect_success_count == 0
    events = await restarted.events_after(waiting.run_id)
    second_recovery = create_controlled_task_composition().create_runtime(factory)
    await recover_runtime(second_recovery)
    assert len(await restarted.events_after(waiting.run_id)) == len(events)
    # Simulate a second Runtime holding a stale command id from its earlier scan.
    await restarted._execute_command(command_id)
    assert len(await restarted.events_after(waiting.run_id)) == len(events)


async def test_startup_recovery_executes_committed_approved_command(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/approved.db")
    composition = create_controlled_task_composition()
    first = composition.create_runtime(factory)
    waiting = await first.create(request(), "approved-key")
    gate = await first.get_gate(waiting.pending_gate_id or "")
    async with factory.begin() as session:
        command = await session.get(SideEffectCommandRecord, gate.command_id)
        gate_record = await session.get(HumanGateRecord, gate.gate_id)
        run = await session.get(RunRecord, waiting.run_id)
        assert command is not None and gate_record is not None and run is not None
        command.status = "approved"
        gate_record.status = "approved"
        run.status = "running"
    restarted = create_controlled_task_composition(resources=composition.resources).create_runtime(
        factory
    )
    assert await recover_runtime(restarted) == []
    assert (await restarted.inspect(waiting.run_id)).status.value == "succeeded"


class BlockingWriteAdapter(MockResourceWriteAdapter):
    def __init__(self, resources: dict[str, dict[str, object]]) -> None:
        super().__init__(resources)  # type: ignore[arg-type]
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, *, payload: dict[str, object], idempotency_key: str) -> ToolResult:
        self.started.set()
        await self.release.wait()
        return await super().execute(payload=payload, idempotency_key=idempotency_key)


async def test_concurrent_approve_observes_in_flight_command(tmp_path: Path) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/approve.db")
    resources = {key: value.copy() for key, value in DEFAULT_RESOURCES.items()}
    adapter = BlockingWriteAdapter(resources)

    def adapter_factory(_: Mapping[str, Any]) -> BlockingWriteAdapter:
        return adapter

    first = create_controlled_task_composition(
        resources=resources,
        write_adapter_factory=adapter_factory,
    ).create_runtime(factory)
    waiting = await first.create(request(), "approve-key")
    gate_id = waiting.pending_gate_id or ""
    decision = HumanGateDecisionRequest(
        decision="approved", decided_by="approver", roles=["approver"], comment="ok"
    )
    first_task = asyncio.create_task(first.decide(gate_id, decision))
    await adapter.started.wait()
    duplicate_runtime = create_controlled_task_composition().create_runtime(factory)
    duplicate = await duplicate_runtime.decide(gate_id, decision)
    assert duplicate.status.value == "running"
    adapter.release.set()
    completed = await first_task
    assert completed.status.value == "succeeded"
    assert adapter.success_count == 1
    assert all(
        event.error_code != "SIDE_EFFECT_UNKNOWN"
        for event in await first.events_after(waiting.run_id)
    )
