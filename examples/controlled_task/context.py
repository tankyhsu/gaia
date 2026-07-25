"""Deterministic, read-only context for the controlled-task scenario."""

from __future__ import annotations

from datetime import UTC, datetime

from gaia.contracts.models import ContextDocument, ContextEnvelope
from gaia.sdk.context import ContextQuery, RunSession


class MockContextProvider:
    def __init__(self, mode: str = "normal") -> None:
        self._mode = mode

    async def get_context(self, *, session: RunSession, query: ContextQuery) -> ContextEnvelope:
        del session
        if self._mode == "missing_evidence":
            return ContextEnvelope(
                documents=[], structured_facts=[], access_scope=[], gaps=["evidence_missing"]
            )
        if query.organization not in {"org-alpha", "org-beta"}:
            return ContextEnvelope(
                documents=[], structured_facts=[], access_scope=[], gaps=["scope_missing"]
            )
        return ContextEnvelope(
            documents=[
                ContextDocument(
                    source_id="evidence-controlled-task",
                    title="Controlled Task Operating Rules",
                    version="1.0.0",
                    valid_until=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
                    excerpt="Controlled task evidence.",
                )
            ],
            structured_facts=[],
            access_scope=["org-alpha", "org-beta"],
            gaps=[],
        )
