"""Programmatic Alembic entry point for framework-owned operational tables."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

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
