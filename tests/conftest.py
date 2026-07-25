from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gaia.persistence.database import dispose_initialized_databases

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
async def dispose_test_databases() -> None:
    yield
    await dispose_initialized_databases()
