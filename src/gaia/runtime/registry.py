"""Runtime composition helpers."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.runtime.dependencies import RuntimeDependencies
from gaia.runtime.engine import RuntimeEngine


def create_runtime(
    factory: async_sessionmaker[AsyncSession], dependencies: RuntimeDependencies
) -> RuntimeEngine:
    return RuntimeEngine(factory, dependencies)
