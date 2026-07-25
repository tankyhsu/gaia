"""Explicit M1 built-in starter declarations without runtime side effects."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from gaia.components.core import (
    ComponentDescriptor,
    ComponentKind,
    ComponentRegistry,
    ComponentResolver,
    ComponentScope,
)
from gaia.config import resolve_secret
from gaia.config.models import GaiaApplicationConfig
from gaia.sdk.events import InProcessEventPublisher
from gaia.starters.core import (
    AutoConfigurationCondition,
    GaiaStarter,
    OnImportAvailable,
    OnProperty,
    StarterDescriptor,
)


@dataclass(frozen=True)
class BuiltinStarter:
    descriptor: StarterDescriptor
    kind: ComponentKind
    component_id: str
    property_path: str
    property_value: str

    def defaults(self) -> dict[str, object]:
        if "." not in self.property_path:
            return {}
        keys = self.property_path.split(".")
        result: dict[str, object] = {keys[-1]: self.property_value}
        for key in reversed(keys[:-1]):
            result = {key: result}
        return result

    def conditions(self) -> list[AutoConfigurationCondition]:
        if self.descriptor.starter_id == "core-runtime":
            return [OnImportAvailable("sqlalchemy")]
        if self.descriptor.starter_id == "evaluation-fixtures":
            return [OnImportAvailable("json")]
        return [OnProperty(self.property_path, self.property_value)]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        # An application-provided component of the same kind is an explicit replacement.
        if any(item.kind == self.kind for item in registry.descriptors()):
            return
        registry.register(
            ComponentDescriptor(
                component_id=self.component_id,
                kind=self.kind,
                implementation=f"gaia.starters.{self.descriptor.starter_id}",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: {"starter": self.descriptor.starter_id},
        )


@dataclass(frozen=True)
class RedisClientStarter:
    descriptor: StarterDescriptor = StarterDescriptor("redis-client", "1.0.0", ("redis-client",))

    def defaults(self) -> dict[str, object]:
        return {}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return []

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if importlib.util.find_spec("redis") is None:
            raise RuntimeError("CONFIG_OPTIONAL_DEPENDENCY_MISSING:redis")
        from gaia.integrations.redis import redis_client_resource

        registry.register_resource(
            ComponentDescriptor(
                component_id="redis-client",
                kind=ComponentKind.CLIENT,
                implementation="redis.asyncio.Redis",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=(
                    "redis.url",
                    "redis.max_connections",
                    "redis.socket_timeout_seconds",
                    "redis.health_check_interval_seconds",
                ),
                scope=ComponentScope.APPLICATION,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: redis_client_resource(
                resolve_secret(config.redis.url),
                max_connections=config.redis.max_connections,
                socket_timeout_seconds=config.redis.socket_timeout_seconds,
                health_check_interval_seconds=config.redis.health_check_interval_seconds,
            ),
        )


@dataclass(frozen=True)
class RedisStarter:
    descriptor: StarterDescriptor
    kind: ComponentKind
    component_id: str
    property_path: str

    def defaults(self) -> dict[str, object]:
        section = "cache" if self.kind == ComponentKind.CACHE else "rate_limit"
        return {section: {"provider": "redis"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty(self.property_path, "redis")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if any(item.kind == self.kind for item in registry.descriptors()):
            return
        implementation = (
            "gaia.integrations.redis.RedisCacheProvider"
            if self.kind == ComponentKind.CACHE
            else "gaia.integrations.redis.RedisRateLimiter"
        )
        configuration_keys = (
            ("redis.url", "redis.key_prefix", "cache.default_ttl_seconds", "cache.max_ttl_seconds")
            if self.kind == ComponentKind.CACHE
            else ("redis.url", "redis.key_prefix")
        )
        registry.register(
            ComponentDescriptor(
                component_id=self.component_id,
                kind=self.kind,
                implementation=implementation,
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=configuration_keys,
                depends_on=("redis-client",),
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda components: self._build(config, components),
        )

    def _build(
        self,
        config: GaiaApplicationConfig,
        components: ComponentResolver,
    ) -> object:
        from gaia.integrations.redis import RedisCacheProvider, RedisRateLimiter

        client: Any = components["redis-client"]
        if self.kind == ComponentKind.CACHE:
            return RedisCacheProvider(
                client,
                key_prefix=config.redis.key_prefix,
                default_ttl_seconds=config.cache.default_ttl_seconds,
                max_ttl_seconds=config.cache.max_ttl_seconds,
            )
        return RedisRateLimiter(
            client,
            key_prefix=config.redis.key_prefix,
        )


@dataclass(frozen=True)
class InProcessPublisherStarter:
    descriptor: StarterDescriptor = StarterDescriptor(
        "publisher-in-process", "1.0.0", ("event-publisher",)
    )

    def defaults(self) -> dict[str, object]:
        return {"outbox": {"publisher": "in-process"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("outbox.publisher", "in-process")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if any(item.kind == ComponentKind.EVENT_PUBLISHER for item in registry.descriptors()):
            return
        registry.register(
            ComponentDescriptor(
                component_id="publisher-in-process",
                kind=ComponentKind.EVENT_PUBLISHER,
                implementation="gaia.sdk.events.InProcessEventPublisher",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: InProcessEventPublisher(),
        )


@dataclass(frozen=True)
class OutboxPostgresStarter:
    descriptor: StarterDescriptor = StarterDescriptor("outbox-postgres", "1.0.0", ("outbox",))

    def defaults(self) -> dict[str, object]:
        return {"outbox": {"provider": "postgres"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("outbox.provider", "postgres")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        from gaia.capabilities.outbox import OutboxRuntimeFactory

        if any(item.kind == ComponentKind.OUTBOX for item in registry.descriptors()):
            return
        registry.register(
            ComponentDescriptor(
                component_id="outbox-postgres",
                kind=ComponentKind.OUTBOX,
                implementation="gaia.capabilities.outbox.OutboxRuntimeFactory",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=(
                    "outbox.batch_size",
                    "outbox.lease_seconds",
                    "outbox.max_attempts",
                    "outbox.retry_delay_seconds",
                ),
                depends_on=("persistence-postgres", "publisher-in-process"),
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: OutboxRuntimeFactory(
                batch_size=config.outbox.batch_size,
                lease_seconds=config.outbox.lease_seconds,
                max_attempts=config.outbox.max_attempts,
                retry_delay_seconds=config.outbox.retry_delay_seconds,
            ),
        )


@dataclass(frozen=True)
class FilePromptStarter:
    descriptor: StarterDescriptor = StarterDescriptor("prompt-file", "1.0.0", ("prompt",))

    def defaults(self) -> dict[str, object]:
        return {"prompt": {"provider": "file", "root": "prompts"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("prompt.provider", "file")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        from gaia.integrations.prompt_files import FilePromptProvider

        if any(item.kind == ComponentKind.PROMPT for item in registry.descriptors()):
            return
        registry.register(
            ComponentDescriptor(
                component_id="prompt-file",
                kind=ComponentKind.PROMPT,
                implementation="gaia.integrations.prompt_files.FilePromptProvider",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=("prompt.root",),
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: FilePromptProvider(config.prompt.root),
        )


@dataclass(frozen=True)
class PostgresPromptStarter:
    descriptor: StarterDescriptor = StarterDescriptor(
        "prompt-postgres",
        "1.0.0",
        ("prompt",),
    )

    def defaults(self) -> dict[str, object]:
        return {"prompt": {"provider": "postgres"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("prompt.provider", "postgres")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        from gaia.integrations.prompt_postgres import prompt_registry_resource

        if any(item.kind == ComponentKind.PROMPT for item in registry.descriptors()):
            return
        operational = config.stores.operational
        registry.register_resource(
            ComponentDescriptor(
                component_id="prompt-postgres",
                kind=ComponentKind.PROMPT,
                implementation="gaia.integrations.prompt_postgres.PostgresPromptRegistry",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=(
                    "runtime.database_url",
                    "stores.operational.pool_size",
                    "stores.operational.max_overflow",
                ),
                depends_on=("persistence-postgres",),
                scope=ComponentScope.APPLICATION,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: prompt_registry_resource(
                resolve_secret(config.runtime.database_url),
                pool_size=operational.pool_size,
                max_overflow=operational.max_overflow,
                pool_timeout_seconds=operational.pool_timeout_seconds,
                pool_recycle_seconds=operational.pool_recycle_seconds,
            ),
        )


@dataclass(frozen=True)
class PostgresRagStarter:
    descriptor: StarterDescriptor = StarterDescriptor(
        "rag-postgres",
        "1.0.0",
        ("rag",),
    )

    def defaults(self) -> dict[str, object]:
        return {
            "rag": {"provider": "postgres"},
            "stores": {
                "memory": {"provider": "postgres"},
                "vector": {"provider": "pgvector", "fields": ["text"]},
            },
            "embedding": {"provider": "openai-compatible"},
        }

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("rag.provider", "postgres")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if any(item.kind == ComponentKind.RAG for item in registry.descriptors()):
            return
        from gaia.rag.resources import postgres_rag_resource

        registry.register_resource(
            ComponentDescriptor(
                component_id="rag-postgres",
                kind=ComponentKind.RAG,
                implementation="gaia.rag.RagPipeline",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=(
                    "rag.root",
                    "rag.namespace_prefix",
                    "rag.chunk_size",
                    "rag.chunk_overlap",
                    "rag.candidate_multiplier",
                ),
                depends_on=(
                    "persistence-postgres",
                    "memory-postgres",
                    "vector-pgvector",
                    "embedding-default",
                ),
                scope=ComponentScope.APPLICATION,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: postgres_rag_resource(config),
        )


def _starter(
    identifier: str, capability: str, kind: ComponentKind, component_id: str, path: str, value: str
) -> BuiltinStarter:
    return BuiltinStarter(
        StarterDescriptor(identifier, "1.0.0", (capability,)), kind, component_id, path, value
    )


BUILTIN_STARTERS: dict[str, GaiaStarter] = {
    "core-runtime": _starter(
        "core-runtime",
        "persistence",
        ComponentKind.PERSISTENCE,
        "persistence-default",
        "profile",
        "mock",
    ),
    "model-mock": _starter(
        "model-mock", "model", ComponentKind.MODEL, "model-default", "model.provider", "mock"
    ),
    "model-openai-compatible": _starter(
        "model-openai-compatible",
        "model",
        ComponentKind.MODEL,
        "model-default",
        "model.provider",
        "openai-compatible",
    ),
    "embedding-openai-compatible": _starter(
        "embedding-openai-compatible",
        "embedding",
        ComponentKind.EMBEDDING,
        "embedding-default",
        "embedding.provider",
        "openai-compatible",
    ),
    "workflow-langgraph": _starter(
        "workflow-langgraph",
        "workflow",
        ComponentKind.WORKFLOW,
        "workflow-default",
        "workflow.provider",
        "langgraph",
    ),
    "context-mock": _starter(
        "context-mock",
        "context",
        ComponentKind.CONTEXT,
        "context-default",
        "context.provider",
        "mock",
    ),
    "policy-controlled": _starter(
        "policy-controlled",
        "policy",
        ComponentKind.POLICY,
        "policy-default",
        "policy.provider",
        "controlled",
    ),
    "evaluation-fixtures": _starter(
        "evaluation-fixtures",
        "evaluation",
        ComponentKind.EVALUATION,
        "evaluation-default",
        "profile",
        "mock",
    ),
    "persistence-postgres": _starter(
        "persistence-postgres",
        "persistence",
        ComponentKind.PERSISTENCE,
        "persistence-postgres",
        "stores.operational.provider",
        "postgres",
    ),
    "checkpoint-sqlite": _starter(
        "checkpoint-sqlite",
        "checkpoint",
        ComponentKind.CHECKPOINT,
        "checkpoint-sqlite",
        "stores.checkpoint.provider",
        "sqlite",
    ),
    "checkpoint-postgres": _starter(
        "checkpoint-postgres",
        "checkpoint",
        ComponentKind.CHECKPOINT,
        "checkpoint-postgres",
        "stores.checkpoint.provider",
        "postgres",
    ),
    "memory-postgres": _starter(
        "memory-postgres",
        "memory",
        ComponentKind.MEMORY,
        "memory-postgres",
        "stores.memory.provider",
        "postgres",
    ),
    "vector-pgvector": _starter(
        "vector-pgvector",
        "vector",
        ComponentKind.VECTOR,
        "vector-pgvector",
        "stores.vector.provider",
        "pgvector",
    ),
    "redis-client": RedisClientStarter(),
    "cache-redis": RedisStarter(
        StarterDescriptor("cache-redis", "1.0.0", ("cache",)),
        ComponentKind.CACHE,
        "cache-redis",
        "cache.provider",
    ),
    "rate-limit-redis": RedisStarter(
        StarterDescriptor("rate-limit-redis", "1.0.0", ("rate-limit",)),
        ComponentKind.RATE_LIMIT,
        "rate-limit-redis",
        "rate_limit.provider",
    ),
    "publisher-in-process": InProcessPublisherStarter(),
    "outbox-postgres": OutboxPostgresStarter(),
    "prompt-file": FilePromptStarter(),
    "prompt-postgres": PostgresPromptStarter(),
    "rag-postgres": PostgresRagStarter(),
}


STARTER_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "cache-redis": ("redis-client",),
    "rate-limit-redis": ("redis-client",),
    "outbox-postgres": ("persistence-postgres", "publisher-in-process"),
    "prompt-postgres": ("persistence-postgres",),
    "rag-postgres": (
        "persistence-postgres",
        "memory-postgres",
        "vector-pgvector",
        "embedding-openai-compatible",
    ),
}
