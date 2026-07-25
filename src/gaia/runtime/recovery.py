"""Startup recovery entry point."""

from gaia.runtime.engine import RuntimeEngine


async def recover_runtime(engine: RuntimeEngine) -> list[str]:
    return await engine.startup_recover()
