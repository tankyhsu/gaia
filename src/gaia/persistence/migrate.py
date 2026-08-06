"""Programmatic Alembic entry point for framework-owned operational tables."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from gaia.persistence import migrations
from gaia.persistence.database import ensure_database_parent
from gaia.persistence.urls import sqlalchemy_async_url


def migration_config(database_url: str) -> Config:
    package_path = Path(migrations.__file__).resolve().parent
    config = Config()
    config.set_main_option("script_location", str(package_path))
    config.set_main_option("sqlalchemy.url", sqlalchemy_async_url(database_url))
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    ensure_database_parent(database_url)
    command.upgrade(migration_config(database_url), revision)


def current_head(database_url: str) -> str | None:
    """Return the single head revision the on-disk migration scripts report.

    This only reads `gaia.persistence.migrations`'s script directory via Alembic's
    `ScriptDirectory`; it never touches the database. Tests that assert a freshly-migrated
    database is stamped at "the head" should compare against this instead of a hardcoded
    revision string -- a literal like `"0010_business_builder_runtime"` is guaranteed to go
    stale the next time a migration is added (which is exactly how that assertion went
    stale before), while this stays correct automatically.
    """

    return ScriptDirectory.from_config(migration_config(database_url)).get_current_head()
