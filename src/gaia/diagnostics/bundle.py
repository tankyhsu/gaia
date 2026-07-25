"""Redacted diagnostic bundle export for field delivery."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.persistence.models import (
    HumanGateRecord,
    RunEventRecord,
    RunRecord,
    SideEffectCommandRecord,
)


class DiagnosticExporter:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def export(self, run_id: str) -> dict[str, Any]:
        async with self._factory() as session:
            run = await session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(run_id)
            events = list(
                await session.scalars(
                    select(RunEventRecord)
                    .where(RunEventRecord.run_id == run_id)
                    .order_by(RunEventRecord.sequence)
                )
            )
            gates = list(
                await session.scalars(
                    select(HumanGateRecord).where(HumanGateRecord.run_id == run_id)
                )
            )
            commands = list(
                await session.scalars(
                    select(SideEffectCommandRecord).where(SideEffectCommandRecord.run_id == run_id)
                )
            )
            user = dict(run.user_json)
            user["id"] = _pseudonym(str(user["id"]))
            return {
                "schema_version": "1.0.0",
                "run": {
                    "run_id": run.run_id,
                    "scenario_id": run.scenario_id,
                    "mode": run.mode,
                    "status": run.status,
                    "user": user,
                    "version_bundle": run.version_bundle,
                    "result": run.result_json,
                    "error": run.error_json,
                    "created_at": run.created_at.isoformat(),
                    "updated_at": run.updated_at.isoformat(),
                },
                "events": [
                    {
                        "sequence": item.sequence,
                        "timestamp": item.timestamp.isoformat(),
                        "actor": item.actor,
                        "step": item.step,
                        "status": item.status,
                        "source_refs": item.source_refs,
                        "rule_refs": item.rule_refs,
                        "error_code": item.error_code,
                    }
                    for item in events
                ],
                "human_gates": [
                    {
                        "gate_id": item.gate_id,
                        "command_id": item.command_id,
                        "status": item.status,
                        "risk_level": item.risk_level,
                        "decided": item.decided_at is not None,
                    }
                    for item in gates
                ],
                "side_effect_commands": [
                    {
                        "command_id": item.command_id,
                        "tool_name": item.tool_name,
                        "status": item.status,
                        "risk_level": item.risk_level,
                        "result": item.result_json,
                    }
                    for item in commands
                ],
                "redaction": {
                    "user_id": "sha256 pseudonym",
                    "request_text": "omitted",
                    "secrets": "omitted",
                },
            }


def _pseudonym(value: str) -> str:
    return "user_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
