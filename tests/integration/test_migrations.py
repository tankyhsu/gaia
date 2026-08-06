from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from gaia.persistence.database import dispose_session_factory, initialize_database


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
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "0016_audit_projection",
    )
    # 0015 dropped the SQL execution ledger; 0016 must have replaced the audit
    # half of it, or upgrading a real database silently loses every record of
    # what ran once Temporal's retention window closes on it.
    for audit_table in ("audit_runs", "audit_run_events", "audit_human_gates"):
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (audit_table,),
        ).fetchone() == (audit_table,)
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
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tool_invocations'"
    ).fetchone() == ("tool_invocations",)
    retired_tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                'applications',
                'configuration_revisions',
                'configuration_audits',
                'runs',
                'run_events',
                'run_budgets',
                'human_gates',
                'side_effect_commands',
                'idempotency_records',
                'runtime_leases'
              )
            """
        )
    }
    assert retired_tables == set()
    for table_name in (
        "artifacts",
        "model_invocations",
        "tool_invocations",
        "guardrail_decisions",
    ):
        foreign_tables = {
            row[2]
            for row in connection.execute(
                f"PRAGMA foreign_key_list({table_name})"
            ).fetchall()
        }
        assert "runs" not in foreign_tables
    connection.close()


def test_fresh_schema_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    upgrade(database)
    upgrade(database)
    connection = sqlite3.connect(database)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "runs" not in tables
    assert "runtime_leases" not in tables
    assert "model_invocations" in tables
    connection.close()


async def test_local_auto_create_excludes_sql_runtime_ledger(tmp_path: Path) -> None:
    database = tmp_path / "local.db"
    factory = await initialize_database(f"sqlite+aiosqlite:///{database}")
    await dispose_session_factory(factory)

    connection = sqlite3.connect(database)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    connection.close()

    assert "runs" not in tables
    assert "run_events" not in tables
    assert "human_gates" not in tables
    assert "side_effect_commands" not in tables
    assert "model_invocations" in tables
    assert "guardrail_decisions" in tables
