"""Application-facing rate-limit port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    observed: int


class RateLimiter(Protocol):
    async def consume(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        cost: int = 1,
    ) -> RateLimitDecision: ...
