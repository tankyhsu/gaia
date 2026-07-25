"""Managed PostgreSQL RAG resource used by the built-in Starter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from gaia.config import GaiaApplicationConfig, resolve_secret, resolve_store_url
from gaia.model_gateway import embedding_function_from_config
from gaia.persistence.postgres import PostgresMemoryStore
from gaia.rag.chunking import FixedWindowChunker
from gaia.rag.loaders import LocalFileDocumentLoader
from gaia.rag.parsers import Utf8TextParser
from gaia.rag.pipeline import RagPipeline
from gaia.rag.repository import MemoryRagRepository


@asynccontextmanager
async def postgres_rag_resource(
    config: GaiaApplicationConfig,
) -> AsyncIterator[RagPipeline]:
    memory_url = resolve_store_url(
        config.stores.memory.database_url,
        fallback=resolve_secret(config.runtime.database_url),
    )
    store = PostgresMemoryStore(
        memory_url,
        config.stores.memory,
        config.stores.vector,
        embed=embedding_function_from_config(config),
    )
    async with store.lifespan():
        yield RagPipeline(
            LocalFileDocumentLoader(Path(config.rag.root)),
            Utf8TextParser(),
            FixedWindowChunker(
                chunk_size=config.rag.chunk_size,
                overlap=config.rag.chunk_overlap,
            ),
            MemoryRagRepository(
                store,
                namespace_prefix=config.rag.namespace_prefix,
                candidate_multiplier=config.rag.candidate_multiplier,
            ),
        )
