"""Model and embedding providers."""

from gaia.model_gateway.embeddings import (
    OpenAICompatibleEmbeddingProvider,
    embedding_function_from_config,
)
from gaia.model_gateway.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleProvider",
    "embedding_function_from_config",
]
