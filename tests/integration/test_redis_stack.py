from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.integrations.redis import (
    RedisCacheProvider,
    RedisRateLimiter,
    redis_client_resource,
)

REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = [
    pytest.mark.redis,
    pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set"),
]


async def test_real_redis_cache_ttl_and_atomic_rate_limit() -> None:
    assert REDIS_URL is not None
    prefix = f"gaia-integration-{uuid4()}"
    async with redis_client_resource(
        REDIS_URL,
        max_connections=20,
        socket_timeout_seconds=2,
        health_check_interval_seconds=30,
    ) as client:
        cache = RedisCacheProvider(
            client,
            key_prefix=prefix,
            default_ttl_seconds=1,
            max_ttl_seconds=2,
        )
        limiter = RedisRateLimiter(client, key_prefix=prefix)
        await cache.set("model", "answer", b"cached")
        assert await cache.get("model", "answer") == b"cached"
        await asyncio.sleep(1.1)
        assert await cache.get("model", "answer") is None

        first = await limiter.consume("model", "user-1", limit=1, window_seconds=10)
        second = await limiter.consume("model", "user-1", limit=1, window_seconds=10)
        assert first.allowed is True
        assert second.allowed is False
        assert second.retry_after_seconds > 0


async def test_redis_starters_create_lifecycle_managed_real_adapters() -> None:
    assert REDIS_URL is not None
    application = GaiaApplication(
        GaiaApplicationConfig(
            starters=("cache-redis", "rate-limit-redis"),
            redis={"url": REDIS_URL, "key_prefix": f"gaia-starter-{uuid4()}"},
            cache={"provider": "redis"},
            rate_limit={"provider": "redis"},
        )
    )

    async with application.lifespan() as context:
        client = context.components["redis-client"]
        cache = context.components["cache-redis"]
        limiter = context.components["rate-limit-redis"]
        assert isinstance(cache, RedisCacheProvider)
        assert isinstance(limiter, RedisRateLimiter)
        assert cache._client is client  # noqa: SLF001 - integration wiring assertion
        assert limiter._client is client  # noqa: SLF001 - integration wiring assertion
