"""Configuration-driven persistence resources for a Gaia application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from gaia.config import GaiaApplicationConfig, resolve_secret, resolve_store_url
from gaia.persistence.checkpoint import InMemoryCheckpointProvider, SqliteCheckpointProvider
from gaia.persistence.postgres import PostgresCheckpointProvider, PostgresMemoryStore
from gaia.spi.embedding import EmbeddingFunction
from gaia.spi.memory import MemoryStore


class GaiaPersistenceResources:
    """Own checkpoint and long-term-memory resources selected by configuration."""

    def __init__(
        self,
        config: GaiaApplicationConfig,
        *,
        embed: EmbeddingFunction | None = None,
        database_url: str | None = None,
    ) -> None:
        operational_url = database_url or resolve_secret(config.runtime.database_url)
        checkpoint_url = resolve_store_url(
            config.stores.checkpoint.database_url,
            fallback=operational_url,
        )
        checkpoint_settings = config.stores.checkpoint
        if checkpoint_settings.provider == "postgres":
            self._checkpoint: Any = PostgresCheckpointProvider(checkpoint_url, checkpoint_settings)
        elif checkpoint_settings.provider == "sqlite":
            self._checkpoint = SqliteCheckpointProvider(checkpoint_url)
        else:
            self._checkpoint = InMemoryCheckpointProvider()

        self._memory: PostgresMemoryStore | None = None
        if config.stores.memory.provider == "postgres":
            memory_url = resolve_store_url(
                config.stores.memory.database_url,
                fallback=operational_url,
            )
            self._memory = PostgresMemoryStore(
                memory_url,
                config.stores.memory,
                config.stores.vector,
                embed=embed,
            )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[GaiaPersistenceResources]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(self._checkpoint.lifespan())
            if self._memory is not None:
                await stack.enter_async_context(self._memory.lifespan())
            yield self

    @property
    def checkpointer(self) -> Any:
        return self._checkpoint.saver

    @property
    def memory(self) -> MemoryStore | None:
        return self._memory
