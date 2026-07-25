"""Database URL conversion without leaking credentials."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url


def database_backend(database_url: str) -> str:
    driver = make_url(database_url).drivername.split("+", maxsplit=1)[0]
    if driver in {"postgres", "postgresql"}:
        return "postgres"
    if driver == "sqlite":
        return "sqlite"
    raise ValueError(f"DATABASE_BACKEND_UNSUPPORTED:{driver}")


def sqlalchemy_async_url(database_url: str) -> str:
    url = make_url(database_url)
    backend = database_backend(database_url)
    if backend == "postgres":
        url = url.set(drivername="postgresql+psycopg")
    elif "+" not in url.drivername:
        url = url.set(drivername="sqlite+aiosqlite")
    return _render(url)


def psycopg_url(database_url: str) -> str:
    if database_backend(database_url) != "postgres":
        raise ValueError("POSTGRES_URL_REQUIRED")
    return _render(make_url(database_url).set(drivername="postgresql"))


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)
