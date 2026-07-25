"""Managed PostgreSQL checkpoint and long-term memory providers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from gaia.config.models import CheckpointStoreSettings, MemoryStoreSettings, VectorStoreSettings
from gaia.persistence.urls import psycopg_url
from gaia.sdk.embedding import EmbeddingFunction
from gaia.sdk.memory import MemoryItem

if TYPE_CHECKING:
    from langgraph.store.postgres.base import PostgresIndexConfig


class PostgresCheckpointProvider:
    """Own a pooled LangGraph PostgresSaver and its lifecycle."""

    def __init__(self, database_url: str, settings: CheckpointStoreSettings) -> None:
        self._database_url = psycopg_url(database_url)
        self._settings = settings
        self._pool: Any | None = None
        self._saver: Any | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[PostgresCheckpointProvider]:
        if self._saver is not None:
            raise RuntimeError("CHECKPOINT_PROVIDER_ALREADY_ACTIVE")
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as error:
            raise RuntimeError("POSTGRES_EXTRA_REQUIRED") from error
        try:
            self._pool = ConnectionPool(
                self._database_url,
                min_size=self._settings.pool_min_size,
                max_size=self._settings.pool_max_size,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            await asyncio.to_thread(self._pool.open, wait=True)
            self._saver = PostgresSaver(self._pool)
            if self._settings.auto_setup:
                await asyncio.to_thread(self._saver.setup)
            yield self
        finally:
            if self._pool is not None:
                await asyncio.to_thread(self._pool.close)
            self._pool = None
            self._saver = None

    @property
    def saver(self) -> Any:
        if self._saver is None:
            raise RuntimeError("CHECKPOINT_PROVIDER_NOT_STARTED")
        return self._saver


class PostgresMemoryStore:
    """Framework wrapper over LangGraph's durable PostgresStore and pgvector index."""

    def __init__(
        self,
        database_url: str,
        memory: MemoryStoreSettings,
        vector: VectorStoreSettings,
        *,
        embed: EmbeddingFunction | None = None,
    ) -> None:
        self._database_url = psycopg_url(database_url)
        self._memory = memory
        self._vector = vector
        self._embed = embed
        self._store: Any | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[PostgresMemoryStore]:
        if self._store is not None:
            raise RuntimeError("MEMORY_STORE_ALREADY_ACTIVE")
        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore
        except ImportError as error:
            raise RuntimeError("POSTGRES_EXTRA_REQUIRED") from error
        index: PostgresIndexConfig | None = None
        if self._vector.provider == "pgvector":
            if self._embed is None:
                raise ValueError("MEMORY_EMBEDDING_PROVIDER_REQUIRED")
            index = cast(
                "PostgresIndexConfig",
                {
                    "dims": self._vector.dimensions,
                    "embed": self._embed,
                    "fields": list(self._vector.fields),
                    "distance_type": self._vector.distance_type,
                    "ann_index_config": {
                        "kind": self._vector.index_kind,
                        "vector_type": self._vector.vector_type,
                    },
                },
            )
        manager = AsyncPostgresStore.from_conn_string(
            self._database_url,
            pool_config={
                "min_size": self._memory.pool_min_size,
                "max_size": self._memory.pool_max_size,
            },
            index=index,
        )
        async with manager as store:
            self._store = store
            if self._memory.auto_setup:
                await self._store.setup()
            try:
                yield self
            finally:
                self._store = None

    def _active(self) -> Any:
        if self._store is None:
            raise RuntimeError("MEMORY_STORE_NOT_STARTED")
        return self._store

    async def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        *,
        index: list[str] | bool | None = None,
    ) -> None:
        selected_index: Any = index
        await self._active().aput(namespace, key, value, index=selected_index)

    async def get(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None:
        item = await self._active().aget(namespace, key)
        return None if item is None else _memory_item(item)

    async def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[MemoryItem]:
        items = await self._active().asearch(
            namespace_prefix,
            query=query,
            filter=filters,
            limit=limit,
            offset=offset,
        )
        return [_memory_item(item) for item in items]

    async def delete(self, namespace: tuple[str, ...], key: str) -> None:
        await self._active().adelete(namespace, key)


def _memory_item(item: Any) -> MemoryItem:
    return MemoryItem(
        namespace=tuple(item.namespace),
        key=str(item.key),
        value=dict(item.value),
        created_at=item.created_at,
        updated_at=item.updated_at,
        score=getattr(item, "score", None),
    )
