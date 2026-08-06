"""Run the Temporal SDK development server used by ``make demo``."""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path

from temporalio.testing import WorkflowEnvironment

from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)

GAIA_SEARCH_ATTRIBUTES = (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)


async def _serve(*, host: str, port: int, database_path: Path) -> None:
    environment = await WorkflowEnvironment.start_local(
        ip=host,
        port=port,
        dev_server_database_filename=str(database_path),
        search_attributes=GAIA_SEARCH_ATTRIBUTES,
    )
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopped.set)
    try:
        await stopped.wait()
    finally:
        await environment.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7233)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_serve(host=args.host, port=args.port, database_path=args.database))


if __name__ == "__main__":
    main()
