"""Async SQLAlchemy database setup for Gaia business records."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gaia.persistence.models import Base
from gaia.persistence.urls import database_backend, sqlalchemy_async_url

_initialized_factories: list[async_sessionmaker[AsyncSession]] = []


def ensure_database_parent(database_url: str) -> None:
    url = make_url(sqlalchemy_async_url(database_url))
    database = url.database
    if not url.drivername.startswith("sqlite") or database is None or database in {"", ":memory:"}:
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _engine_options(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
) -> dict[str, int | bool]:
    if database_backend(database_url) != "postgres":
        return {}
    return {
        "pool_pre_ping": True,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout_seconds,
        "pool_recycle": pool_recycle_seconds,
    }


def create_session_factory(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        sqlalchemy_async_url(database_url),
        **_engine_options(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout_seconds=pool_timeout_seconds,
            pool_recycle_seconds=pool_recycle_seconds,
        ),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
    auto_create: bool = True,
) -> async_sessionmaker[AsyncSession]:
    """Test/local bootstrap; production startup uses the same schema through Alembic."""
    ensure_database_parent(database_url)
    engine = create_async_engine(
        sqlalchemy_async_url(database_url),
        **_engine_options(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout_seconds=pool_timeout_seconds,
            pool_recycle_seconds=pool_recycle_seconds,
        ),
    )
    if auto_create:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    _initialized_factories.append(factory)
    return factory


async def dispose_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Dispose the AsyncEngine owned by a factory after all sessions are closed."""
    engine = factory.kw.get("bind")
    if engine is not None:
        await engine.dispose()
    if factory in _initialized_factories:
        _initialized_factories.remove(factory)


@asynccontextmanager
async def session_factory_resource(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
    auto_create: bool = True,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = await initialize_database(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout_seconds=pool_timeout_seconds,
        pool_recycle_seconds=pool_recycle_seconds,
        auto_create=auto_create,
    )
    try:
        yield factory
    finally:
        await dispose_session_factory(factory)


async def dispose_initialized_databases() -> None:
    """Test-only safety net for factories created by initialize_database()."""
    for factory in list(_initialized_factories):
        await dispose_session_factory(factory)


class UnitOfWork:
    """Explicit transaction boundary used by runtime services."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> UnitOfWork:
        self.session = self._factory()
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.session is None:
            return
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
