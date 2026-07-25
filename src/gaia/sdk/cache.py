"""Application-facing cache port."""

from __future__ import annotations

from typing import Protocol


class CacheProvider(Protocol):
    async def get(self, namespace: str, key: str) -> bytes | None: ...

    async def set(
        self,
        namespace: str,
        key: str,
        value: bytes,
        *,
        ttl_seconds: int | None = None,
    ) -> None: ...

    async def delete(self, namespace: str, key: str) -> bool: ...
