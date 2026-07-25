from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade(database: Path) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")


def test_legacy_event_counter_is_backfilled(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('0002_run_event_counter');
        CREATE TABLE runs (run_id VARCHAR(64) PRIMARY KEY, event_sequence INTEGER NOT NULL);
        CREATE TABLE run_events (
            event_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), sequence INTEGER
        );
        INSERT INTO runs VALUES ('legacy-run', 0);
        INSERT INTO run_events VALUES ('one', 'legacy-run', 1);
        INSERT INTO run_events VALUES ('seven', 'legacy-run', 7);
        """
    )
    connection.commit()
    connection.close()
    upgrade(database)
    connection = sqlite3.connect(database)
    counter = connection.execute(
        "SELECT event_sequence FROM runs WHERE run_id = 'legacy-run'"
    ).fetchone()
    assert counter == (7,)
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "0009_guardrail_decisions",
    )
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'outbox_events'"
    ).fetchone() == ("outbox_events",)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'prompt_versions'"
    ).fetchone() == ("prompt_versions",)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'model_invocations'"
    ).fetchone() == ("model_invocations",)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'guardrail_decisions'"
    ).fetchone() == ("guardrail_decisions",)
    retired_tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('applications', 'configuration_revisions', 'configuration_audits')
            """
        )
    }
    assert retired_tables == set()
    connection.close()


def test_fresh_schema_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    upgrade(database)
    upgrade(database)
