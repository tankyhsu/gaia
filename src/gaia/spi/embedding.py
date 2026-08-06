"""Embedding provider port exposed to Gaia applications."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

EmbeddingFunction = Callable[[Sequence[str]], list[list[float]] | Awaitable[list[list[float]]]]


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
