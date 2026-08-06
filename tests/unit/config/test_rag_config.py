import pytest
from pydantic import ValidationError

from gaia.config import GaiaApplicationConfig


def test_postgres_rag_requires_memory_vector_and_embedding() -> None:
    with pytest.raises(ValidationError, match="stores.memory"):
        GaiaApplicationConfig.model_validate({"rag": {"provider": "postgres"}})


def test_postgres_rag_accepts_complete_dependency_set() -> None:
    config = GaiaApplicationConfig.model_validate(
        {
            "rag": {"provider": "postgres", "chunk_size": 512, "chunk_overlap": 64},
            "stores": {
                "memory": {"provider": "postgres"},
                "vector": {"provider": "pgvector", "dimensions": 64},
            },
            "embedding": {
                "provider": "openai-compatible",
                "base_url": "https://embedding.example/v1",
                "api_key": {"env": "EMBEDDING_KEY"},
                "dimensions": 64,
            },
        }
    )
    assert config.rag.provider == "postgres"


def test_external_http_rag_requires_address_and_redacts_optional_key() -> None:
    with pytest.raises(ValidationError, match="rag.base_url"):
        GaiaApplicationConfig.model_validate({"rag": {"provider": "external-http"}})

    config = GaiaApplicationConfig.model_validate(
        {
            "rag": {
                "provider": "external-http",
                "base_url": "https://knowledge.example.com",
                "api_key": {"file": "/run/secrets/rag"},
            }
        }
    )

    assert config.rag.provider == "external-http"
    assert config.redacted()["rag"]["api_key"] == {"file": "***"}
