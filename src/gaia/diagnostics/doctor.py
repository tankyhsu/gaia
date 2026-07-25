"""Explicit connectivity diagnostics for a configured Gaia application."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gaia.application import GaiaApplication
from gaia.config import SecretRef, resolve_secret
from gaia.persistence.database import ensure_database_parent
from gaia.persistence.urls import sqlalchemy_async_url


class DoctorStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DoctorCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    check_id: str
    status: DoctorStatus
    message: str
    operator_action: str
    duration_ms: int


class DoctorReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    application_name: str
    profile: str
    checked_at: datetime
    checks: tuple[DoctorCheck, ...]


async def run_doctor(application: GaiaApplication) -> DoctorReport:
    started = perf_counter()
    await application.configure()
    checks = [
        DoctorCheck(
            check_id="configuration",
            status=DoctorStatus.PASSED,
            message="Configuration and component graph are valid.",
            operator_action="No action required.",
            duration_ms=_elapsed_ms(started),
        )
    ]

    database_urls = _database_targets(application)
    for check_id, value in database_urls:
        checks.append(
            await _run_check(
                check_id,
                partial(_probe_database_target, value),
                passed_message="Database connection succeeded.",
                operator_action="Check the database secret, network route, and server health.",
            )
        )

    config = application.config
    if config.cache.provider == "redis" or config.rate_limit.provider == "redis":
        checks.append(
            await _run_check(
                "redis",
                lambda: _probe_redis(
                    resolve_secret(config.redis.url),
                    timeout_seconds=config.redis.socket_timeout_seconds,
                ),
                passed_message="Redis connection succeeded.",
                operator_action="Check the Redis secret, network route, and optional dependency.",
            )
        )
    else:
        checks.append(_skipped("redis", "Redis capabilities are disabled."))

    if config.model.provider == "mock":
        checks.append(_skipped("model", "The deterministic mock model needs no network probe."))
    else:
        checks.append(
            await _run_check(
                "model",
                lambda: _probe_openai_endpoint(
                    base_url=config.model.base_url,
                    api_key=config.model.api_key,
                    timeout_seconds=config.model.timeout_seconds,
                ),
                passed_message="Model endpoint connection succeeded.",
                operator_action=(
                    "Check the model base URL, API key, network route, and service health."
                ),
            )
        )

    if config.embedding.provider == "disabled":
        checks.append(_skipped("embedding", "Embedding is disabled."))
    else:
        checks.append(
            await _run_check(
                "embedding",
                lambda: _probe_openai_endpoint(
                    base_url=config.embedding.base_url,
                    api_key=config.embedding.api_key,
                    timeout_seconds=config.embedding.timeout_seconds,
                ),
                passed_message="Embedding endpoint connection succeeded.",
                operator_action=(
                    "Check the embedding base URL, API key, network route, and service health."
                ),
            )
        )

    return DoctorReport(
        ok=all(item.status != DoctorStatus.FAILED for item in checks),
        application_name=config.application.name,
        profile=config.profile,
        checked_at=datetime.now(UTC),
        checks=tuple(checks),
    )


def _database_targets(
    application: GaiaApplication,
) -> tuple[tuple[str, str | SecretRef], ...]:
    config = application.config
    targets: list[tuple[str, str | SecretRef]] = [
        ("database.operational", config.runtime.database_url)
    ]
    seen = {str(targets[0][1])}
    for name in ("checkpoint", "memory"):
        store = getattr(config.stores, name)
        if store.provider != "postgres":
            continue
        candidate = store.database_url if store.database_url is not None else targets[0][1]
        if str(candidate) not in seen:
            targets.append((f"database.{name}", candidate))
            seen.add(str(candidate))
    return tuple(targets)


async def _probe_database(database_url: str) -> None:
    ensure_database_parent(database_url)
    engine = create_async_engine(sqlalchemy_async_url(database_url))
    try:
        async with engine.connect() as connection:
            await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=10)
    finally:
        await engine.dispose()


async def _probe_database_target(value: str | SecretRef) -> None:
    await _probe_database(resolve_secret(value))


async def _probe_redis(url: str, *, timeout_seconds: int) -> None:
    try:
        from redis.asyncio import Redis
    except ModuleNotFoundError as error:
        raise RuntimeError("CONFIG_OPTIONAL_DEPENDENCY_MISSING:redis") from error

    client = Redis.from_url(url, socket_timeout=timeout_seconds)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _probe_openai_endpoint(
    *,
    base_url: str | None,
    api_key: SecretRef | None,
    timeout_seconds: int,
) -> None:
    if base_url is None:
        raise ValueError("CONFIG_ENDPOINT_BASE_URL_MISSING")
    secret = resolve_secret(api_key) if api_key is not None else ""
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    async with httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/",
        headers=headers,
        timeout=timeout_seconds,
    ) as client:
        response = await client.get("models")
        response.raise_for_status()


async def _run_check(
    check_id: str,
    probe: Callable[[], Awaitable[Any]],
    *,
    passed_message: str,
    operator_action: str,
) -> DoctorCheck:
    started = perf_counter()
    try:
        await probe()
    except Exception as error:
        return DoctorCheck(
            check_id=check_id,
            status=DoctorStatus.FAILED,
            message=_failure_message(error),
            operator_action=operator_action,
            duration_ms=_elapsed_ms(started),
        )
    return DoctorCheck(
        check_id=check_id,
        status=DoctorStatus.PASSED,
        message=passed_message,
        operator_action="No action required.",
        duration_ms=_elapsed_ms(started),
    )


def _failure_message(error: Exception) -> str:
    value = str(error)
    if "CONFIG_SECRET_UNAVAILABLE" in value:
        return "A required secret reference is unavailable."
    if "CONFIG_OPTIONAL_DEPENDENCY_MISSING" in value:
        return "A required optional dependency is not installed."
    if isinstance(error, TimeoutError):
        return "The dependency did not respond before the diagnostic timeout."
    if isinstance(error, httpx.HTTPStatusError):
        return f"The dependency returned HTTP {error.response.status_code}."
    if isinstance(error, httpx.HTTPError):
        return "The dependency endpoint could not be reached."
    return f"The dependency check failed ({error.__class__.__name__})."


def _skipped(check_id: str, message: str) -> DoctorCheck:
    return DoctorCheck(
        check_id=check_id,
        status=DoctorStatus.SKIPPED,
        message=message,
        operator_action="No action required.",
        duration_ms=0,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
