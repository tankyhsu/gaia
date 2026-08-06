"""SQLAlchemy implementation of Gaia's durable audit projection.

This is the store that answers "what actually happened" after Temporal has
deleted the Workflow History it happened in. Everything here is written by the
`record_audit` Activity, so every method must be safe to run twice: Temporal
retries Activities, and it is allowed to.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.persistence.models import (
    AuditHumanGateRecord,
    AuditRunEventRecord,
    AuditRunRecord,
)
from gaia.runtime.contracts import RUN_LIST_DEFAULT_LIMIT, InvalidRunCursor

_CURSOR_SEPARATOR = "|"


def _utc_naive(value: datetime | str) -> datetime:
    """Normalize any timestamp to naive UTC.

    Ordering has to mean the same thing on SQLite (which hands back naive
    datetimes) and PostgreSQL (which hands back aware ones). Rather than keep
    two representations, every timestamp that reaches a comparison -- stored
    column, cursor bound, projected snapshot -- passes through this one rule.
    """

    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def encode_cursor(created_at: datetime, run_id: str) -> str:
    raw = f"{created_at.isoformat()}{_CURSOR_SEPARATOR}{run_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor this store issued, or reject it as malformed."""

    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidRunCursor(cursor) from error
    created_text, separator, run_id = raw.partition(_CURSOR_SEPARATOR)
    if not separator or not run_id:
        raise InvalidRunCursor(cursor)
    try:
        return _utc_naive(created_text), run_id
    except ValueError as error:
        raise InvalidRunCursor(cursor) from error


class SqlAlchemyAuditProjection:
    """Gaia-owned evidence store for Runs, events, and human gates."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        snapshot: dict[str, Any],
        events: list[dict[str, Any]],
        gates: list[dict[str, Any]],
    ) -> None:
        run_id = str(snapshot["run_id"])
        created_at = _utc_naive(str(snapshot["created_at"]))
        updated_at = _utc_naive(str(snapshot["updated_at"]))
        user = snapshot.get("user")
        organization = (
            str(user.get("organization", "")) if isinstance(user, dict) else ""
        )
        highest = max((int(event["sequence"]) for event in events), default=0)

        async with self._session_factory() as session:
            async with session.begin():
                run = await session.get(AuditRunRecord, run_id)
                if run is None:
                    session.add(
                        AuditRunRecord(
                            run_id=run_id,
                            organization=organization,
                            scenario_id=str(snapshot["scenario_id"]),
                            mode=str(snapshot["mode"]),
                            status=str(snapshot["status"]),
                            snapshot_json=snapshot,
                            last_sequence=highest,
                            created_at=created_at,
                            updated_at=updated_at,
                        )
                    )
                elif updated_at >= _utc_naive(run.updated_at):
                    # A retried or out-of-order projection must never move a Run
                    # backwards: the newest evidence wins, older evidence is
                    # dropped rather than allowed to overwrite it.
                    run.status = str(snapshot["status"])
                    run.snapshot_json = snapshot
                    run.updated_at = updated_at
                    run.last_sequence = max(run.last_sequence, highest)

                if events:
                    known = set(
                        (
                            await session.execute(
                                select(AuditRunEventRecord.sequence).where(
                                    AuditRunEventRecord.run_id == run_id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    now = datetime.now(UTC).replace(tzinfo=None)
                    for event in events:
                        sequence = int(event["sequence"])
                        if sequence in known:
                            continue
                        session.add(
                            AuditRunEventRecord(
                                run_id=run_id,
                                sequence=sequence,
                                event_json=event,
                                recorded_at=now,
                            )
                        )

                for gate in gates:
                    await self._project_gate(session, run_id=run_id, gate=gate)

    @staticmethod
    async def _project_gate(
        session: AsyncSession,
        *,
        run_id: str,
        gate: dict[str, Any],
    ) -> None:
        """Project a gate from the Workflow, without letting it grant approval.

        The Workflow is not a trusted source of authorization. Anyone who can
        reach the Temporal namespace can send the `decide` Update with any
        `roles` they like, so a projection that accepted "approved" from the
        Workflow would let that forged decision become the record that
        `execute_command` checks.

        So this path may record a gate, and may record outcomes that *withhold*
        authority (`rejected`, `expired`), but can never move a gate into
        `approved`. Only `record_decision`, called from the authenticated API
        path, can do that.
        """

        gate_id = str(gate["gate_id"])
        status = str(gate["status"])
        if status == "approved":
            # Downgrade the stored document too, not just the column. `get_gate`
            # returns the document, so leaving it saying "approved" would hand
            # the forged decision straight back to the caller that checks it.
            gate = {**gate, "status": "pending", "decided_by": None, "decided_at": None}
            status = "pending"
        existing = await session.get(AuditHumanGateRecord, gate_id)
        if existing is None:
            session.add(
                AuditHumanGateRecord(
                    gate_id=gate_id,
                    run_id=run_id,
                    status=status,
                    gate_json=gate,
                    created_at=_utc_naive(str(gate["created_at"])),
                    recorded_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            return
        if existing.status != "pending" or status in {"pending", "approved"}:
            return
        existing.status = status
        existing.gate_json = gate

    async def record_decision(
        self,
        *,
        gate: dict[str, Any],
        decision: str,
        decided_by: str,
        comment: str | None,
        decided_at: datetime,
    ) -> bool:
        """Record an authenticated human decision. The only way to reach `approved`.

        Returns True when the projection now holds exactly this decision by this
        decider -- including when it already did. The decision is written before
        Temporal is told about it, so a caller whose Temporal call then failed
        has to be able to retry; treating its second attempt as a conflict would
        strand the Run on a gate that Gaia considers decided.

        Returns False when the gate already carries a different decision or
        decider. An existing decision is never overwritten.

        `gate` is the authoritative gate document the caller just read, so a
        decision made before the Workflow's own projection landed still records
        correctly. The projection trails the Workflow by one Activity
        round-trip, and an approver who acts inside that window is approving a
        gate that genuinely exists -- refusing them would be a race, not a
        control.
        """

        gate_id = str(gate["gate_id"])
        async with self._session_factory() as session:
            async with session.begin():
                record = await session.get(AuditHumanGateRecord, gate_id)
                if record is not None and record.status != "pending":
                    return (
                        record.status == decision
                        and record.gate_json.get("decided_by") == decided_by
                    )
                payload = dict(record.gate_json) if record is not None else dict(gate)
                payload["status"] = decision
                payload["decided_by"] = decided_by
                payload["comment"] = comment
                payload["decided_at"] = decided_at.isoformat()
                if record is None:
                    session.add(
                        AuditHumanGateRecord(
                            gate_id=gate_id,
                            run_id=str(gate["run_id"]),
                            status=decision,
                            gate_json=payload,
                            created_at=_utc_naive(str(gate["created_at"])),
                            recorded_at=datetime.now(UTC).replace(tzinfo=None),
                        )
                    )
                    return True
                record.status = decision
                record.gate_json = payload
                return True

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            record = await session.get(AuditRunRecord, run_id)
            return None if record is None else dict(record.snapshot_json)

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: str | None = None,
        scenario_id: str | None = None,
        limit: int = RUN_LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        statement = select(AuditRunRecord)
        if organization is not None:
            statement = statement.where(AuditRunRecord.organization == organization)
        if status is not None:
            statement = statement.where(AuditRunRecord.status == status)
        if scenario_id is not None:
            statement = statement.where(AuditRunRecord.scenario_id == scenario_id)
        if cursor is not None:
            bound_created_at, bound_run_id = decode_cursor(cursor)
            # Keyset, not offset: a Run projected between two page reads must
            # not shift rows across the page boundary and hide evidence.
            statement = statement.where(
                or_(
                    AuditRunRecord.created_at < bound_created_at,
                    and_(
                        AuditRunRecord.created_at == bound_created_at,
                        AuditRunRecord.run_id < bound_run_id,
                    ),
                )
            )
        statement = statement.order_by(
            AuditRunRecord.created_at.desc(),
            AuditRunRecord.run_id.desc(),
        ).limit(limit + 1)

        async with self._session_factory() as session:
            records = list((await session.execute(statement)).scalars().all())
        page = records[:limit]
        next_cursor = (
            encode_cursor(page[-1].created_at, page[-1].run_id)
            if len(records) > limit and page
            else None
        )
        return {
            "items": [dict(record.snapshot_json) for record in page],
            "next_cursor": next_cursor,
        }

    async def events_after(
        self, run_id: str, sequence: int = 0
    ) -> list[dict[str, Any]]:
        statement = (
            select(AuditRunEventRecord)
            .where(
                AuditRunEventRecord.run_id == run_id,
                AuditRunEventRecord.sequence > sequence,
            )
            .order_by(AuditRunEventRecord.sequence)
        )
        async with self._session_factory() as session:
            records = (await session.execute(statement)).scalars().all()
        return [dict(record.event_json) for record in records]

    async def get_gate(self, gate_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            record = await session.get(AuditHumanGateRecord, gate_id)
            return None if record is None else dict(record.gate_json)

    async def gates_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Every gate `run_id` opened, oldest first -- via `ix_audit_human_gates_run`.

        This is what answers "who approved this Run" for a Run whose own
        snapshot never carries `decided_by` and whose in-flight fields
        (`pending_gate_id`, `action_plan[].gate_id`) are cleared the moment
        the Run completes. `get_gate` cannot help there: it requires a gate
        id the caller does not have.
        """

        statement = (
            select(AuditHumanGateRecord)
            .where(AuditHumanGateRecord.run_id == run_id)
            .order_by(AuditHumanGateRecord.created_at)
        )
        async with self._session_factory() as session:
            records = (await session.execute(statement)).scalars().all()
        return [dict(record.gate_json) for record in records]
