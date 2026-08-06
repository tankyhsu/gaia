"""Concrete bindings and adapters for application infrastructure."""

from gaia.integrations.api_key import ApiKeyAuthnProvider
from gaia.integrations.events import InProcessEventPublisher
from gaia.integrations.guardrails_ai import (
    GuardrailsAIValidator,
    GuardrailsMetadataFactory,
)
from gaia.integrations.guardrails_presidio import PresidioGuardrail
from gaia.integrations.oidc import JwtAuthnProvider
from gaia.integrations.prompt_files import FilePromptProvider, PromptNotFoundError
from gaia.integrations.prompt_postgres import (
    PostgresPromptRegistry,
    PromptRegistryConflict,
    PromptRegistryNotFound,
)
from gaia.integrations.redis import (
    RedisCacheProvider,
    RedisRateLimiter,
    redis_client_resource,
)

__all__ = [
    "ApiKeyAuthnProvider",
    "InProcessEventPublisher",
    "RedisCacheProvider",
    "RedisRateLimiter",
    "GuardrailsAIValidator",
    "GuardrailsMetadataFactory",
    "PresidioGuardrail",
    "JwtAuthnProvider",
    "FilePromptProvider",
    "PromptNotFoundError",
    "PostgresPromptRegistry",
    "PromptRegistryConflict",
    "PromptRegistryNotFound",
    "redis_client_resource",
]
