"""Framework-wide, strictly validated application configuration."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from gaia.contracts.models import RunMode, WriteMode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigOrigin(StrEnum):
    DEFAULT = "default"
    STARTER_DEFAULT = "starter_default"
    YAML = "yaml"
    PROFILE = "profile"
    ENVIRONMENT = "environment"
    CLI = "cli"


class SecretRef(StrictModel):
    env: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def one_reference(self) -> SecretRef:
        if bool(self.env) == bool(self.file):
            raise ValueError("exactly one of env or file is required")
        return self

    def redacted(self) -> dict[str, str]:
        return {"env": self.env} if self.env else {"file": "***"}


class ImportedStarterRef(StrictModel):
    import_: Annotated[
        str,
        Field(alias="import"),
        StringConstraints(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$"),
    ]


class ApplicationSettings(StrictModel):
    name: str = "gaia-app"
    version: str = "0.1.0"


class RuntimeSettings(StrictModel):
    database_url: str | SecretRef = "sqlite+aiosqlite:///./var/gaia.db"
    max_steps: int = Field(default=32, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    environment: RunMode = RunMode.MOCK
    write_mode: WriteMode | None = None

    @model_validator(mode="after")
    def sandbox_never_enables_unattended_writes(self) -> RuntimeSettings:
        if self.environment == RunMode.SANDBOX and self.write_mode == WriteMode.ENABLED:
            raise ValueError("sandbox runtime.write_mode cannot be enabled")
        return self

    def effective_write_mode(self) -> WriteMode:
        if self.write_mode is not None:
            return self.write_mode
        return {
            RunMode.MOCK: WriteMode.ENABLED,
            RunMode.SANDBOX: WriteMode.APPROVAL_REQUIRED,
            RunMode.CUSTOMER: WriteMode.DISABLED,
        }[self.environment]


class OperationalStoreSettings(StrictModel):
    provider: Literal["sqlite", "postgres"] = "sqlite"
    auto_create: bool = True
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: int = Field(default=30, ge=1)
    pool_recycle_seconds: int = Field(default=1800, ge=1)


class CheckpointStoreSettings(StrictModel):
    provider: Literal["sqlite", "postgres", "memory"] = "sqlite"
    database_url: str | SecretRef | None = None
    auto_setup: bool = True
    pool_min_size: int = Field(default=1, ge=1)
    pool_max_size: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_pool(self) -> CheckpointStoreSettings:
        if self.pool_max_size < self.pool_min_size:
            raise ValueError("checkpoint pool_max_size must be >= pool_min_size")
        return self


class MemoryStoreSettings(StrictModel):
    provider: Literal["disabled", "postgres"] = "disabled"
    database_url: str | SecretRef | None = None
    auto_setup: bool = True
    pool_min_size: int = Field(default=1, ge=1)
    pool_max_size: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_pool(self) -> MemoryStoreSettings:
        if self.pool_max_size < self.pool_min_size:
            raise ValueError("memory pool_max_size must be >= pool_min_size")
        return self


class VectorStoreSettings(StrictModel):
    provider: Literal["disabled", "pgvector"] = "disabled"
    dimensions: int = Field(default=1536, ge=1, le=65535)
    distance_type: Literal["cosine", "l2", "inner_product"] = "cosine"
    index_kind: Literal["hnsw", "ivfflat"] = "hnsw"
    vector_type: Literal["vector", "halfvec"] = "vector"
    fields: tuple[str, ...] = ("$",)


class StoresSettings(StrictModel):
    operational: OperationalStoreSettings = Field(default_factory=OperationalStoreSettings)
    checkpoint: CheckpointStoreSettings = Field(default_factory=CheckpointStoreSettings)
    memory: MemoryStoreSettings = Field(default_factory=MemoryStoreSettings)
    vector: VectorStoreSettings = Field(default_factory=VectorStoreSettings)

    @model_validator(mode="after")
    def validate_store_dependencies(self) -> StoresSettings:
        if self.vector.provider == "pgvector" and self.memory.provider != "postgres":
            raise ValueError("pgvector requires stores.memory.provider=postgres")
        return self


class RedisSettings(StrictModel):
    url: str | SecretRef = "redis://127.0.0.1:6379/0"
    key_prefix: str = Field(
        default="gaia",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    max_connections: int = Field(default=20, ge=1, le=1000)
    socket_timeout_seconds: int = Field(default=2, ge=1, le=60)
    health_check_interval_seconds: int = Field(default=30, ge=1, le=3600)


class CacheSettings(StrictModel):
    provider: Literal["disabled", "redis"] = "disabled"
    default_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    max_ttl_seconds: int = Field(default=86400, ge=1, le=604800)

    @model_validator(mode="after")
    def validate_ttl(self) -> CacheSettings:
        if self.default_ttl_seconds > self.max_ttl_seconds:
            raise ValueError("cache default_ttl_seconds must be <= max_ttl_seconds")
        return self


class RateLimitSettings(StrictModel):
    provider: Literal["disabled", "redis"] = "disabled"


class OutboxSettings(StrictModel):
    provider: Literal["disabled", "postgres"] = "disabled"
    publisher: Literal["in-process"] = "in-process"
    batch_size: int = Field(default=50, ge=1, le=1000)
    lease_seconds: int = Field(default=30, ge=1, le=3600)
    max_attempts: int = Field(default=8, ge=1, le=100)
    retry_delay_seconds: int = Field(default=5, ge=0, le=3600)


class ModelSettings(StrictModel):
    provider: str = "mock"
    model_id: str = "deterministic-mock"
    base_url: str | None = None
    api_key: SecretRef | None = None
    timeout_seconds: int = Field(default=2, ge=1)


class EmbeddingSettings(StrictModel):
    provider: Literal["disabled", "openai-compatible"] = "disabled"
    model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    base_url: str | None = None
    api_key: SecretRef | None = None
    dimensions: int | None = Field(default=None, ge=1, le=65535)
    batch_size: int = Field(default=32, ge=1, le=256)
    timeout_seconds: int = Field(default=30, ge=1)


class ProviderSettings(StrictModel):
    provider: str


class WorkflowSettings(ProviderSettings):
    provider: str = "langgraph"


class ContextSettings(ProviderSettings):
    provider: str = "mock"


class PolicySettings(ProviderSettings):
    provider: str = "controlled"
    human_gate_ttl_seconds: int = Field(default=86400, ge=1)


class EvaluationSettings(StrictModel):
    cases: str | None = None


class PromptSettings(StrictModel):
    provider: Literal["disabled", "file", "postgres"] = "disabled"
    root: str = "prompts"


class RagSettings(StrictModel):
    provider: Literal["disabled", "postgres"] = "disabled"
    root: str = "documents"
    namespace_prefix: str = Field(
        default="gaia-rag",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    chunk_size: int = Field(default=1200, ge=128, le=10000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    candidate_multiplier: int = Field(default=4, ge=1, le=20)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> RagSettings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("rag chunk_overlap must be smaller than chunk_size")
        return self


class GaiaApplicationConfig(StrictModel):
    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    profile: str = "mock"
    starters: tuple[str | ImportedStarterRef, ...] = (
        "core-runtime",
        "model-mock",
        "workflow-langgraph",
        "context-mock",
        "policy-controlled",
        "prompt-file",
    )
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    stores: StoresSettings = Field(default_factory=StoresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    policy: PolicySettings = Field(default_factory=PolicySettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)

    @model_validator(mode="after")
    def validate_embedding_dimensions(self) -> GaiaApplicationConfig:
        if self.model.provider == "openai-compatible" and self.model.base_url is None:
            raise ValueError("openai-compatible model requires model.base_url")
        if self.embedding.provider == "openai-compatible":
            if self.embedding.base_url is None:
                raise ValueError("openai-compatible embedding requires embedding.base_url")
            if self.embedding.api_key is None:
                raise ValueError("openai-compatible embedding requires embedding.api_key")
        if (
            self.stores.vector.provider == "pgvector"
            and self.embedding.dimensions is not None
            and self.embedding.dimensions != self.stores.vector.dimensions
        ):
            raise ValueError("embedding dimensions must match stores.vector.dimensions")
        if self.outbox.provider == "postgres" and self.stores.operational.provider != "postgres":
            raise ValueError("postgres outbox requires stores.operational.provider=postgres")
        if self.prompt.provider == "postgres" and self.stores.operational.provider != "postgres":
            raise ValueError(
                "postgres prompt registry requires stores.operational.provider=postgres"
            )
        if self.rag.provider == "postgres":
            if self.stores.memory.provider != "postgres":
                raise ValueError("postgres rag requires stores.memory.provider=postgres")
            if self.stores.vector.provider != "pgvector":
                raise ValueError("postgres rag requires stores.vector.provider=pgvector")
            if self.embedding.provider == "disabled":
                raise ValueError("postgres rag requires an embedding provider")
        return self

    def redacted(self) -> dict[str, Any]:
        value = self.model_dump(mode="json", by_alias=True)
        value["runtime"]["write_mode"] = self.runtime.effective_write_mode().value
        if isinstance(self.runtime.database_url, SecretRef):
            value["runtime"]["database_url"] = self.runtime.database_url.redacted()
        if isinstance(self.redis.url, SecretRef):
            value["redis"]["url"] = self.redis.url.redacted()
        for store_name in ("checkpoint", "memory"):
            store = getattr(self.stores, store_name)
            if isinstance(store.database_url, SecretRef):
                value["stores"][store_name]["database_url"] = store.database_url.redacted()
        if self.model.api_key:
            value["model"]["api_key"] = self.model.api_key.redacted()
        if self.embedding.api_key:
            value["embedding"]["api_key"] = self.embedding.api_key.redacted()
        return value

    def stable_hash(self) -> str:
        # SecretRef contains only an unresolved reference. Hashing that reference preserves
        # configuration identity without resolving or persisting the secret value.
        payload = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
