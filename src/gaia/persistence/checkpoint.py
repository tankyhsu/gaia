"""Managed local checkpoint providers used by the persistence resource bundle."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy.engine import make_url

from gaia.persistence.urls import sqlalchemy_async_url


class InMemoryCheckpointProvider:
    def __init__(self) -> None:
        self._saver = InMemorySaver()

    @property
    def saver(self) -> InMemorySaver:
        return self._saver

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[InMemoryCheckpointProvider]:
        yield self


class SqliteCheckpointProvider:
    def __init__(self, database_url: str) -> None:
        database = make_url(sqlalchemy_async_url(database_url)).database
        if database is None:
            raise ValueError("SQLITE_DATABASE_PATH_REQUIRED")
        self._database = database
        self._connection: sqlite3.Connection | None = None
        self._saver: SqliteSaver | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[SqliteCheckpointProvider]:
        if self._saver is not None:
            raise RuntimeError("CHECKPOINT_PROVIDER_ALREADY_ACTIVE")
        if self._database != ":memory:":
            Path(self._database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database, check_same_thread=False)
        self._saver = SqliteSaver(self._connection)
        try:
            yield self
        finally:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._saver = None

    @property
    def saver(self) -> Any:
        if self._saver is None:
            raise RuntimeError("CHECKPOINT_PROVIDER_NOT_STARTED")
        return self._saver
