from __future__ import annotations

from typing import Any

import pytest

from gaia.integrations.redis import RedisCacheProvider, RedisRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}
        self.counters: dict[str, int] = {}
        self.ping_count = 0

    async def ping(self) -> bool:
        self.ping_count += 1
        return True

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: bytes, *, ex: int) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def eval(self, script: str, number_of_keys: int, *values: Any) -> list[int]:
        del script, number_of_keys
        key, cost, window = str(values[0]), int(values[1]), int(values[2])
        self.counters[key] = self.counters.get(key, 0) + cost
        return [self.counters[key], window]


async def test_redis_cache_uses_namespaced_keys_and_bounded_ttl() -> None:
    client = FakeRedis()
    cache = RedisCacheProvider(
        client,
        key_prefix="test",
        default_ttl_seconds=60,
        max_ttl_seconds=120,
    )

    await cache.set("model", "answer", b"cached")

    assert await cache.get("model", "answer") == b"cached"
    assert client.expirations["test:cache:model:answer"] == 60
    assert await cache.delete("model", "answer") is True
    assert await cache.get("model", "answer") is None
    with pytest.raises(ValueError, match="ttl_seconds"):
        await cache.set("model", "answer", b"cached", ttl_seconds=121)
    await cache.set("tenant:one", "answer:v1", b"encoded")
    assert client.values["test:cache:tenant%3Aone:answer%3Av1"] == b"encoded"


async def test_redis_rate_limiter_returns_deterministic_fixed_window_decisions() -> None:
    client = FakeRedis()
    limiter = RedisRateLimiter(client, key_prefix="test")

    first = await limiter.consume("model", "user-1", limit=2, window_seconds=30)
    second = await limiter.consume("model", "user-1", limit=2, window_seconds=30)
    rejected = await limiter.consume("model", "user-1", limit=2, window_seconds=30)

    assert (first.allowed, first.remaining, first.retry_after_seconds) == (True, 1, 0)
    assert (second.allowed, second.remaining, second.retry_after_seconds) == (True, 0, 0)
    assert (rejected.allowed, rejected.remaining, rejected.retry_after_seconds) == (False, 0, 30)
    with pytest.raises(ValueError, match="must be positive"):
        await limiter.consume("model", "user-1", limit=0, window_seconds=30)
