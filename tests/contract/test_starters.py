from pathlib import Path

import pytest

from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.starters import BUILTIN_STARTERS, AutoConfigurator


def test_builtin_starters_have_descriptors_and_match_report() -> None:
    config = GaiaApplicationConfig(
        starters=("core-runtime", "model-mock", "workflow-langgraph", "policy-controlled")
    )
    registry, report = AutoConfigurator(BUILTIN_STARTERS).configure(config)
    assert len(report.positive) == 4
    assert report.negative == ()
    assert {item.component_id for item in registry.descriptors()} == {
        "persistence-default",
        "model-default",
        "workflow-default",
        "policy-default",
    }


def test_postgres_starter_defaults_preserve_nested_configuration_paths() -> None:
    assert BUILTIN_STARTERS["persistence-postgres"].defaults() == {
        "stores": {"operational": {"provider": "postgres"}}
    }
    assert BUILTIN_STARTERS["checkpoint-postgres"].defaults() == {
        "stores": {"checkpoint": {"provider": "postgres"}}
    }
    assert BUILTIN_STARTERS["memory-postgres"].defaults() == {
        "stores": {"memory": {"provider": "postgres"}}
    }
    assert BUILTIN_STARTERS["vector-pgvector"].defaults() == {
        "stores": {"vector": {"provider": "pgvector"}}
    }
    assert BUILTIN_STARTERS["embedding-openai-compatible"].defaults() == {
        "embedding": {"provider": "openai-compatible"}
    }
    assert BUILTIN_STARTERS["cache-redis"].defaults() == {"cache": {"provider": "redis"}}
    assert BUILTIN_STARTERS["rate-limit-redis"].defaults() == {"rate_limit": {"provider": "redis"}}
    assert BUILTIN_STARTERS["outbox-postgres"].defaults() == {"outbox": {"provider": "postgres"}}
    assert BUILTIN_STARTERS["prompt-file"].defaults() == {
        "prompt": {"provider": "file", "root": "prompts"}
    }
    assert BUILTIN_STARTERS["prompt-postgres"].defaults() == {"prompt": {"provider": "postgres"}}
    assert BUILTIN_STARTERS["rag-postgres"].defaults() == {
        "rag": {"provider": "postgres"},
        "stores": {
            "memory": {"provider": "postgres"},
            "vector": {"provider": "pgvector", "fields": ["text"]},
        },
        "embedding": {"provider": "openai-compatible"},
    }


async def test_prompt_file_starter_constructs_provider_without_reading_files(
    tmp_path: Path,
) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  starters: [prompt-file]\n"
        "  prompt:\n"
        "    provider: file\n"
        f"    root: {tmp_path / 'missing-prompts'}\n"
    )

    application = GaiaApplication.from_config(config)
    configured = await application.configure()

    assert [item.component_id for item in configured.descriptors] == ["prompt-file"]
    async with application.lifespan() as started:
        assert started.components["prompt-file"].root == tmp_path / "missing-prompts"


async def test_infrastructure_starters_build_public_runtime_components(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n  starters:\n    - cache-redis\n    - rate-limit-redis\n    - outbox-postgres\n"
    )

    application = GaiaApplication.from_config(config)

    configured = await application.configure()
    assert configured.components == {}
    assert {item.component_id for item in configured.descriptors} >= {
        "redis-client",
        "cache-redis",
        "rate-limit-redis",
        "publisher-in-process",
        "outbox-postgres",
    }

    implementations = {item.component_id: item.implementation for item in configured.descriptors}
    assert implementations["redis-client"] == "redis.asyncio.Redis"
    assert implementations["cache-redis"] == "gaia.integrations.redis.RedisCacheProvider"
    assert implementations["rate-limit-redis"] == "gaia.integrations.redis.RedisRateLimiter"
    assert implementations["outbox-postgres"] == ("gaia.capabilities.outbox.OutboxRuntimeFactory")


async def test_programmatic_application_expands_outbox_dependencies() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "starters": ["outbox-postgres"],
            "runtime": {"database_url": "postgresql://gaia:secret@localhost/gaia"},
            "stores": {"operational": {"provider": "postgres"}},
            "outbox": {"provider": "postgres"},
        }
    )

    context = await GaiaApplication(config).configure()

    assert {item.component_id for item in context.descriptors} == {
        "persistence-postgres",
        "publisher-in-process",
        "outbox-postgres",
    }


async def test_programmatic_application_expands_rag_dependencies() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "starters": ["rag-postgres"],
            "runtime": {"database_url": "postgresql://gaia:secret@localhost/gaia"},
            "stores": {
                "operational": {"provider": "postgres"},
                "memory": {"provider": "postgres"},
                "vector": {"provider": "pgvector", "dimensions": 64},
            },
            "embedding": {
                "provider": "openai-compatible",
                "base_url": "https://embedding.example/v1",
                "api_key": {"env": "EMBEDDING_KEY"},
                "dimensions": 64,
            },
            "rag": {"provider": "postgres"},
        }
    )

    context = await GaiaApplication(config).configure()

    assert {item.component_id for item in context.descriptors} == {
        "embedding-default",
        "memory-postgres",
        "persistence-postgres",
        "vector-pgvector",
        "rag-postgres",
    }


async def test_redis_starter_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gaia.starters.builtin.importlib.util.find_spec", lambda _name: None)
    application = GaiaApplication(
        GaiaApplicationConfig(
            starters=("redis-client",),
        )
    )

    with pytest.raises(RuntimeError, match="CONFIG_OPTIONAL_DEPENDENCY_MISSING:redis"):
        await application.configure()
