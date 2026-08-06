"""Explicit M1 built-in starter declarations without runtime side effects."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, cast

from gaia.components.core import (
    ComponentDescriptor,
    ComponentKind,
    ComponentRegistry,
    ComponentResolver,
    ComponentScope,
)
from gaia.config import resolve_secret
from gaia.config.models import GaiaApplicationConfig
from gaia.integrations.events import InProcessEventPublisher
from gaia.spi.model import ModelProvider
from gaia.spi.prompt import PromptProvider
from gaia.spi.rag import Retriever
from gaia.starters.core import (
    AutoConfigurationCondition,
    GaiaStarter,
    OnImportAvailable,
    OnProperty,
    OnScenarioModules,
    StarterDescriptor,
)
from gaia.starters.scenario_discovery import discover_scenarios


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
class ModelMockStarter:
    """Registers the framework's deterministic mock `ModelProvider` for MODEL.

    Unlike `BuiltinStarter`, this registers a real `ModelProvider` instance (see
    `gaia.model_gateway.mock.DeterministicMockProvider`) rather than a placeholder marker
    dict, so `scenario-runtime`'s port-narrowing check (`_model_provider_from`) picks it
    up and model-backed declarative scenarios work without an application-supplied
    `model_provider`.
    """

    descriptor: StarterDescriptor = StarterDescriptor("model-mock", "1.0.0", ("model",))

    def defaults(self) -> dict[str, object]:
        return {"model": {"provider": "mock"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("model.provider", "mock")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        # An application-provided component of the same kind is an explicit replacement.
        if any(item.kind == ComponentKind.MODEL for item in registry.descriptors()):
            return
        from gaia.model_gateway.mock import DeterministicMockProvider

        registry.register(
            ComponentDescriptor(
                component_id="model-default",
                kind=ComponentKind.MODEL,
                implementation="gaia.model_gateway.mock.DeterministicMockProvider",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: DeterministicMockProvider(),
        )


@dataclass(frozen=True)
class ModelOpenAICompatibleStarter:
    """Registers a real `OpenAICompatibleProvider` for MODEL.

    `OpenAICompatibleProvider` opens a fresh `httpx.AsyncClient` per call (see
    `gaia.model_gateway.openai_compatible`) rather than holding one open for the life of
    the application, so it is a plain object with nothing to release -- `register`
    (`ComponentScope.STATIC`) is the correct call here, not `register_resource`.

    The resolved API key is passed straight into the provider's constructor and lives
    only as that instance's private attribute. It is never placed on the
    `ComponentDescriptor` (only the unresolved `SecretRef` lives in `config.model.api_key`,
    which `GaiaApplicationConfig.redacted()` already redacts before it reaches the
    Actuator snapshot), so it cannot leak through `actuator_snapshot()`.
    """

    descriptor: StarterDescriptor = StarterDescriptor(
        "model-openai-compatible", "1.0.0", ("model",)
    )

    def defaults(self) -> dict[str, object]:
        return {"model": {"provider": "openai-compatible"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("model.provider", "openai-compatible")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if any(item.kind == ComponentKind.MODEL for item in registry.descriptors()):
            return
        from gaia.model_gateway.openai_compatible import OpenAICompatibleProvider

        api_key = config.model.api_key
        registry.register(
            ComponentDescriptor(
                component_id="model-default",
                kind=ComponentKind.MODEL,
                implementation="gaia.model_gateway.openai_compatible.OpenAICompatibleProvider",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=("model.base_url", "model.model_id", "model.api_key"),
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: OpenAICompatibleProvider(
                api_key=resolve_secret(api_key) if api_key is not None else None
            ),
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
                implementation="gaia.integrations.events.InProcessEventPublisher",
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


@dataclass(frozen=True)
class ExternalHttpRagStarter:
    descriptor: StarterDescriptor = StarterDescriptor(
        "rag-external-http",
        "1.0.0",
        ("rag",),
    )

    def defaults(self) -> dict[str, object]:
        return {"rag": {"provider": "external-http"}}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnProperty("rag.provider", "external-http")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        if any(item.kind == ComponentKind.RAG for item in registry.descriptors()):
            return
        from gaia.rag.external import ExternalHttpRetriever

        api_key = config.rag.api_key
        registry.register(
            ComponentDescriptor(
                component_id="rag-external-http",
                kind=ComponentKind.RAG,
                implementation="gaia.rag.ExternalHttpRetriever",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                configuration_keys=(
                    "rag.base_url",
                    "rag.endpoint",
                    "rag.api_key",
                    "rag.timeout_seconds",
                ),
                scope=ComponentScope.STATIC,
                reason=f"starter:{self.descriptor.starter_id}",
            ),
            lambda _components: ExternalHttpRetriever(
                base_url=cast(str, config.rag.base_url),
                endpoint=config.rag.endpoint,
                api_key=resolve_secret(api_key) if api_key else None,
                timeout_seconds=config.rag.timeout_seconds,
            ),
        )


def _model_provider_from(candidate: Any) -> ModelProvider | None:
    """Narrow `candidate` to a `ModelProvider`, treating anything else (including the
    placeholder marker dicts the still-marker-only WORKFLOW/CONTEXT/POLICY `BuiltinStarter`
    instances register for other kinds, should one ever end up here) as absent.

    `model-mock` / `model-openai-compatible` (`ModelMockStarter` /
    `ModelOpenAICompatibleStarter`) register real `ModelProvider` instances, so for MODEL
    this check ordinarily just confirms the shape of a real provider; it stays in place as
    the general contract for whatever ends up registered under `ComponentKind.MODEL`.

    `ModelProvider` is a plain `typing.Protocol`, not `@runtime_checkable`, so
    `isinstance(candidate, ModelProvider)` would raise `TypeError`. A duck-type check on
    its three methods stands in for it instead.
    """
    if (
        hasattr(candidate, "health")
        and hasattr(candidate, "generate_structured")
        and hasattr(candidate, "generate_stream")
    ):
        return cast(ModelProvider, candidate)
    return None


def _prompt_provider_from(candidate: Any) -> PromptProvider | None:
    """`PromptProvider` is `@runtime_checkable`, so `isinstance` is safe and exact here."""
    return candidate if isinstance(candidate, PromptProvider) else None


def _retriever_from(candidate: Any) -> Retriever | None:
    """`Retriever` is `@runtime_checkable`, so `isinstance` is safe and exact here."""
    return candidate if isinstance(candidate, Retriever) else None


@dataclass(frozen=True)
class ScenarioRuntimeStarter:
    """Registers the `RuntimeAssembler` built in A3 as a `RUNTIME` component.

    Optional collaborators (model provider / prompt provider / retriever) are resolved
    from already-registered components of kind MODEL / PROMPT / RAG, but only injected
    when the resolved instance actually satisfies the corresponding port. As of A4b, the
    built-in MODEL starters (`model-mock` / `model-openai-compatible`, see
    `ModelMockStarter` / `ModelOpenAICompatibleStarter`) register real `ModelProvider`
    instances, so model-backed declarative scenarios work end to end with no
    application-supplied `model_provider`. PROMPT still only gets a real instance from
    `prompt-file` / `prompt-postgres`; CONTEXT and POLICY (via the generic
    `BuiltinStarter`) still register placeholder marker dicts, so a context- or
    policy-dependent declarative path is not wired up yet.
    """

    descriptor: StarterDescriptor = StarterDescriptor(
        "scenario-runtime", "1.0.0", ("runtime-assembly",)
    )

    def defaults(self) -> dict[str, object]:
        return {}

    def conditions(self) -> list[AutoConfigurationCondition]:
        return [OnScenarioModules()]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        from gaia.runtime.assembly import RuntimeAssembler

        discovered = discover_scenarios(config.scenarios.modules)
        descriptors = registry.descriptors()
        model_id = next(
            (item.component_id for item in descriptors if item.kind == ComponentKind.MODEL),
            None,
        )
        prompt_id = next(
            (item.component_id for item in descriptors if item.kind == ComponentKind.PROMPT),
            None,
        )
        rag_id = next(
            (item.component_id for item in descriptors if item.kind == ComponentKind.RAG),
            None,
        )
        depends_on = tuple(
            component_id
            for component_id in (model_id, prompt_id, rag_id)
            if component_id is not None
        )

        def _build(components: ComponentResolver) -> Any:
            return RuntimeAssembler(
                config=config,
                scenario_handlers=discovered.scenario_handlers,
                tool_handlers=discovered.tool_handlers,
                model_provider=_model_provider_from(
                    components.get(model_id) if model_id else None
                ),
                prompt_provider=_prompt_provider_from(
                    components.get(prompt_id) if prompt_id else None
                ),
                retriever=_retriever_from(components.get(rag_id) if rag_id else None),
                # `handoff_handlers` / `continuation_handlers` come straight from the
                # `@agent_handler` / `@continuation_handler` functions discovery found.
                # `allowed_handoffs` here carries only the agent-to-agent routes (each
                # agent's own declared `allowed_handoffs`); `RuntimeAssembler.create_engine`
                # merges in each scenario's own `"scenario"` entry per runner.
                handoff_handlers=discovered.agent_handlers,
                continuation_handlers=discovered.continuation_handlers,
                allowed_handoffs=discovered.agent_routes,
            )

        registry.register(
            ComponentDescriptor(
                component_id="runtime-assembler",
                kind=ComponentKind.RUNTIME,
                implementation="gaia.runtime.assembly.RuntimeAssembler",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                depends_on=depends_on,
                configuration_keys=("scenarios.modules", "runtime.environment"),
                reason="scenarios.modules is configured",
            ),
            _build,
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
    "model-mock": ModelMockStarter(),
    "model-openai-compatible": ModelOpenAICompatibleStarter(),
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
    "rag-external-http": ExternalHttpRagStarter(),
    "scenario-runtime": ScenarioRuntimeStarter(),
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
