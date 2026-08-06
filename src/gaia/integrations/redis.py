"""Gaia policy bindings around the official redis-py asyncio client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from gaia.spi.rate_limit import RateLimitDecision

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCRBY', KEYS[1], ARGV[1])
local ttl = redis.call('TTL', KEYS[1])
if current == tonumber(ARGV[1]) or ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    ttl = tonumber(ARGV[2])
end
return {current, ttl}
"""


def _part(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return quote(normalized, safe="")


@asynccontextmanager
async def redis_client_resource(
    url: str,
    *,
    max_connections: int,
    socket_timeout_seconds: int,
    health_check_interval_seconds: int,
) -> AsyncIterator[Any]:
    try:
        from redis.asyncio import Redis
    except ModuleNotFoundError as error:
        raise RuntimeError("CONFIG_OPTIONAL_DEPENDENCY_MISSING:redis") from error

    client = Redis.from_url(
        url,
        decode_responses=False,
        max_connections=max_connections,
        socket_timeout=socket_timeout_seconds,
        health_check_interval=health_check_interval_seconds,
    )
    try:
        await client.ping()
        yield client
    finally:
        await client.aclose()


class RedisCacheProvider:
    def __init__(
        self,
        client: Any,
        *,
        key_prefix: str,
        default_ttl_seconds: int,
        max_ttl_seconds: int,
    ) -> None:
        self._client = client
        self._key_prefix = _part(key_prefix, "key_prefix")
        self._default_ttl_seconds = default_ttl_seconds
        self._max_ttl_seconds = max_ttl_seconds

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._key_prefix}:cache:{_part(namespace, 'namespace')}:{_part(key, 'key')}"

    async def get(self, namespace: str, key: str) -> bytes | None:
        value = await self._client.get(self._key(namespace, key))
        if value is None or isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")

    async def set(
        self,
        namespace: str,
        key: str,
        value: bytes,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        if ttl < 1 or ttl > self._max_ttl_seconds:
            raise ValueError(f"ttl_seconds must be between 1 and {self._max_ttl_seconds}")
        await self._client.set(self._key(namespace, key), value, ex=ttl)

    async def delete(self, namespace: str, key: str) -> bool:
        return bool(await self._client.delete(self._key(namespace, key)))


class RedisRateLimiter:
    def __init__(self, client: Any, *, key_prefix: str) -> None:
        self._client = client
        self._key_prefix = _part(key_prefix, "key_prefix")

    async def consume(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        cost: int = 1,
    ) -> RateLimitDecision:
        if limit < 1 or window_seconds < 1 or cost < 1:
            raise ValueError("limit, window_seconds and cost must be positive")
        redis_key = (
            f"{self._key_prefix}:rate-limit:{_part(namespace, 'namespace')}:"
            f"{_part(key, 'key')}:{window_seconds}"
        )
        raw = await self._client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            redis_key,
            cost,
            window_seconds,
        )
        observed, ttl = int(raw[0]), max(0, int(raw[1]))
        return RateLimitDecision(
            allowed=observed <= limit,
            limit=limit,
            remaining=max(0, limit - observed),
            retry_after_seconds=0 if observed <= limit else ttl,
            observed=observed,
        )
