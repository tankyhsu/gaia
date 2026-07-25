from pathlib import Path

import pytest

from gaia.persistence.database import dispose_session_factory, initialize_database


@pytest.mark.asyncio
async def test_initialize_database_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "var" / "gaia.db"

    factory = await initialize_database(f"sqlite+aiosqlite:///{database_path}")
    try:
        assert database_path.is_file()
    finally:
        await dispose_session_factory(factory)
