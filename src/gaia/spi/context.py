"""Read-only ContextProvider port."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from gaia.contracts.models import ContextEnvelope


class ContextQuery(BaseModel):
    organization: str
    resource_id: str | None = None


class RunSession(BaseModel):
    run_id: str
    user_id: str
    organization: str
    roles: list[str]


class ContextProvider(Protocol):
    async def get_context(self, *, session: RunSession, query: ContextQuery) -> ContextEnvelope: ...
