from __future__ import annotations

import pytest
from pydantic import ValidationError

from gaia.config import GaiaApplicationConfig, resolve_secret, resolve_store_url
from gaia.persistence.urls import database_backend, psycopg_url, sqlalchemy_async_url


def test_postgres_store_configuration_and_secret_redaction() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "runtime": {"database_url": {"env": "DATABASE_URL"}},
            "stores": {
                "operational": {"provider": "postgres", "auto_create": False},
                "checkpoint": {"provider": "postgres"},
                "memory": {"provider": "postgres"},
                "vector": {"provider": "pgvector", "dimensions": 4},
            },
            "embedding": {
                "provider": "openai-compatible",
                "base_url": "https://embedding.example/v1",
                "api_key": {"env": "EMBEDDING_API_KEY"},
                "dimensions": 4,
            },
        }
    )

    assert resolve_secret(
        config.runtime.database_url,
        environ={"DATABASE_URL": "postgresql://gaia:secret@localhost/gaia"},
    ).endswith("@localhost/gaia")
    assert config.redacted()["runtime"]["database_url"] == {"env": "DATABASE_URL"}
    assert config.redacted()["embedding"]["api_key"] == {"env": "EMBEDDING_API_KEY"}
    assert config.stores.operational.auto_create is False


def test_redis_and_outbox_configuration_is_strict_and_redacted() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "stores": {"operational": {"provider": "postgres"}},
            "redis": {"url": {"env": "GAIA_REDIS_URL"}, "key_prefix": "tenant-a"},
            "cache": {"provider": "redis", "default_ttl_seconds": 60},
            "rate_limit": {"provider": "redis"},
            "outbox": {"provider": "postgres", "publisher": "in-process"},
        }
    )

    assert config.redacted()["redis"]["url"] == {"env": "GAIA_REDIS_URL"}
    with pytest.raises(ValidationError, match="postgres outbox requires"):
        GaiaApplicationConfig(outbox={"provider": "postgres"})
    with pytest.raises(ValidationError, match="default_ttl_seconds"):
        GaiaApplicationConfig(cache={"default_ttl_seconds": 120, "max_ttl_seconds": 60})


def test_pgvector_requires_postgres_memory_and_valid_pools() -> None:
    with pytest.raises(ValidationError, match="pgvector requires"):
        GaiaApplicationConfig(stores={"vector": {"provider": "pgvector"}})
    with pytest.raises(ValidationError, match="pool_max_size"):
        GaiaApplicationConfig(stores={"checkpoint": {"pool_min_size": 5, "pool_max_size": 1}})
    with pytest.raises(ValidationError, match="embedding dimensions"):
        GaiaApplicationConfig(
            stores={
                "memory": {"provider": "postgres"},
                "vector": {"provider": "pgvector", "dimensions": 64},
            },
            embedding={
                "provider": "openai-compatible",
                "base_url": "https://embedding.example/v1",
                "api_key": {"env": "EMBEDDING_API_KEY"},
                "dimensions": 128,
            },
        )


def test_external_model_and_embedding_require_explicit_endpoint_configuration() -> None:
    with pytest.raises(ValidationError, match="model.base_url"):
        GaiaApplicationConfig(model={"provider": "openai-compatible"})
    with pytest.raises(ValidationError, match="embedding.base_url"):
        GaiaApplicationConfig(embedding={"provider": "openai-compatible"})
    with pytest.raises(ValidationError, match="embedding.api_key"):
        GaiaApplicationConfig(
            embedding={
                "provider": "openai-compatible",
                "base_url": "https://embedding.example/v1",
            }
        )


def test_store_url_fallback_and_database_url_conversion() -> None:
    source = "postgres://gaia:p%40ss@localhost:5432/gaia"

    assert database_backend(source) == "postgres"
    assert sqlalchemy_async_url(source).startswith("postgresql+psycopg://")
    assert psycopg_url(source).startswith("postgresql://")
    assert "p%40ss" in psycopg_url(source)
    assert resolve_store_url(None, source) == source


def test_missing_secret_has_stable_error() -> None:
    config = GaiaApplicationConfig(runtime={"database_url": {"env": "MISSING_DATABASE"}})
    with pytest.raises(ValueError, match="CONFIG_SECRET_UNAVAILABLE:MISSING_DATABASE"):
        resolve_secret(config.runtime.database_url, environ={})
