"""Durable long-term memory port exposed to Gaia applications."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class MemoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    namespace: tuple[str, ...]
    key: str
    value: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    score: float | None = None


class MemoryStore(Protocol):
    async def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        *,
        index: list[str] | bool | None = None,
    ) -> None: ...

    async def get(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None: ...

    async def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[MemoryItem]: ...

    async def delete(self, namespace: tuple[str, ...], key: str) -> None: ...
