"""Framework-wide, strictly validated application configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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


class PolicyOverrideSettings(StrictModel):
    """A config-driven, monotonic tightening of one scenario's `ExecutionPolicy`.

    Every field here may only make the target policy *stricter* than the
    `@scenario`-declared baseline -- never looser. See
    `gaia.runtime.policy.apply_policy_override` for the enforcement and the
    fingerprinted version evidence this produces. `None` (the default) means
    "leave this dimension alone"; `deny_tools` defaults to empty for the same
    reason.
    """

    write_mode: WriteMode | None = None
    max_steps: int | None = None
    max_model_calls: int | None = None
    max_duration_seconds: int | None = None
    deny_tools: tuple[str, ...] = ()


class RuntimeSettings(StrictModel):
    database_url: str | SecretRef = "sqlite+aiosqlite:///./var/gaia.db"
    execution: RuntimeExecutionSettings = Field(
        default_factory=lambda: RuntimeExecutionSettings()
    )
    max_steps: int = Field(default=32, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    environment: RunMode = RunMode.MOCK
    write_mode: WriteMode | None = None
    policy_overrides: Mapping[str, PolicyOverrideSettings] = {}

    @model_validator(mode="after")
    def enforce_environment_execution_boundary(self) -> RuntimeSettings:
        if self.environment == RunMode.SANDBOX and self.write_mode == WriteMode.ENABLED:
            raise ValueError("sandbox runtime.write_mode cannot be enabled")
        if self.environment == RunMode.CUSTOMER and self.execution.provider != "temporal":
            raise ValueError(
                "customer runtime requires runtime.execution.provider=temporal; "
                "Gaia production execution is durable by design"
            )
        return self

    def effective_write_mode(self) -> WriteMode:
        if self.write_mode is not None:
            return self.write_mode
        return {
            RunMode.MOCK: WriteMode.ENABLED,
            RunMode.SANDBOX: WriteMode.APPROVAL_REQUIRED,
            RunMode.CUSTOMER: WriteMode.DISABLED,
        }[self.environment]

class RuntimeExecutionSettings(StrictModel):
    provider: Literal["in_process", "temporal"] = "in_process"
    namespace: str = "default"
    task_queue: str = "gaia-runtime"
    server_address: str = "127.0.0.1:7233"
    tls_enabled: bool = False
    task_timeout_seconds: int = Field(default=30, ge=1, le=3600)
    max_concurrent_workflows: int = Field(default=200, ge=1, le=1000)
    # Set both to run Workers under pinned deployment versioning: an in-flight
    # Run stays on the build it started on, so deploying a changed Workflow only
    # affects new Runs. Left unset, every Worker serves every Run and an
    # incompatible Workflow change strands Runs that are already in flight --
    # including any parked on a HumanGate, whose default TTL is a full day.
    deployment_name: str | None = Field(default=None, min_length=1)
    build_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def deployment_versioning_is_all_or_nothing(self) -> RuntimeExecutionSettings:
        if (self.deployment_name is None) != (self.build_id is None):
            raise ValueError(
                "runtime.execution.deployment_name and build_id must be set together; "
                "one without the other silently disables pinned versioning"
            )
        return self


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


class ObservabilitySettings(StrictModel):
    """Select the external trace backend without moving execution truth into Gaia."""

    provider: Literal["local", "langfuse"] = "local"
    base_url: str = Field(default="http://localhost:3000", min_length=1)
    public_key: SecretRef | None = None
    secret_key: SecretRef | None = None
    environment: str = Field(
        default="development",
        pattern=r"^[a-z0-9_-]{1,40}$",
    )
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def langfuse_requires_credentials(self) -> ObservabilitySettings:
        if self.environment.startswith("langfuse"):
            raise ValueError("observability.environment cannot start with 'langfuse'")
        if self.provider == "langfuse":
            if self.public_key is None:
                raise ValueError(
                    "langfuse observability requires observability.public_key"
                )
            if self.secret_key is None:
                raise ValueError(
                    "langfuse observability requires observability.secret_key"
                )
        return self


class PromptSettings(StrictModel):
    provider: Literal["disabled", "file", "postgres"] = "disabled"
    root: str = "prompts"


class RagSettings(StrictModel):
    provider: Literal["disabled", "postgres", "external-http"] = "disabled"
    root: str = "documents"
    base_url: str | None = None
    endpoint: str = Field(default="/v1/retrieve", pattern=r"^/[^\s]*$")
    api_key: SecretRef | None = None
    timeout_seconds: int = Field(default=10, ge=1, le=120)
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
        if self.provider == "external-http" and self.base_url is None:
            raise ValueError("external-http rag requires rag.base_url")
        return self


class ScenarioSettings(StrictModel):
    """Declarative discovery of @scenario / @read_tool / @write_tool modules."""

    modules: tuple[str, ...] = ()


# JWT algorithms this framework will ever configure for OIDC token verification.
# Deliberately asymmetric-only: the signing key (private) and verification key
# (public, published as JWKS) differ, so a caller who only has the public JWKS
# can never forge a signature. Symmetric algorithms (`HS*`) are excluded on
# purpose -- if they were allowed, an attacker who knows the IdP's public JWKS
# (published, not secret) could sign their own token with `alg=HS256` using
# that public key *as* the HMAC secret, and a verifier that naively looked up
# "the key for this alg" would accept it. This is the classic RS256/HS256 "key
# confusion" attack. `none` is excluded for the equally classic reason: it
# requires no signature at all. See `gaia.integrations.oidc.JwtAuthnProvider`
# for where this allowlist is enforced (never derived from the token itself).
OIDC_ASYMMETRIC_ALGORITHMS: frozenset[str] = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES256K",
        "ES384",
        "ES512",
    }
)


class ClaimMappingSettings(StrictModel):
    """Where in a validated JWT's claims to find identity fields.

    Every IdP places these in a different spot -- Keycloak nests roles under
    `realm_access.roles`, Entra ID uses a flat `groups` claim, Okta typically
    uses a custom claim name entirely. Dotted paths (`"a.b.c"`) address nested
    claims; a single segment (`"groups"`) addresses a top-level claim. There is
    deliberately no framework-wide default that assumes one vendor's layout.
    """

    subject: str = Field(default="sub", min_length=1)
    organization: str = Field(default="org_id", min_length=1)
    roles: str = Field(default="roles", min_length=1)


class AuthnSettings(StrictModel):
    """Config-driven construction of the request-level `AuthnProvider`.

    `provider: "disabled"` (the default) leaves `create_app` to build its own
    default the way it always has (`ApiKeyAuthnProvider`, or whatever is
    passed explicitly via `create_app(authn=...)`) -- this section changes
    nothing until an application opts in. `provider: "oidc"` builds a
    `gaia.integrations.oidc.JwtAuthnProvider` from the fields below: Gaia
    validates the token's signature and standard claims and maps claims to a
    `UserIdentity`; it does not issue tokens, manage users, or grant roles --
    that is the IdP's job (Keycloak, Okta, Entra ID, Ping, ...).
    """

    provider: Literal["disabled", "oidc"] = "disabled"
    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    leeway_seconds: int = Field(default=30, ge=0, le=300)
    algorithms: tuple[str, ...] = ("RS256",)
    jwks_cache_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    jwks_fetch_backoff_seconds: int = Field(default=30, ge=1, le=3600)
    claims: ClaimMappingSettings = Field(default_factory=ClaimMappingSettings)

    @model_validator(mode="after")
    def validate_oidc(self) -> AuthnSettings:
        if self.provider == "oidc":
            if not self.issuer:
                raise ValueError("oidc authn requires authn.issuer")
            if not self.audience:
                raise ValueError("oidc authn requires authn.audience")
            if not self.algorithms:
                raise ValueError("oidc authn requires at least one entry in authn.algorithms")
        for algorithm in self.algorithms:
            if algorithm not in OIDC_ASYMMETRIC_ALGORITHMS:
                raise ValueError(
                    "authn.algorithms must be asymmetric-signature algorithms "
                    f"({sorted(OIDC_ASYMMETRIC_ALGORITHMS)}); rejected {algorithm!r} "
                    "(symmetric algorithms and 'none' let a caller forge or skip "
                    "the signature -- see OIDC_ASYMMETRIC_ALGORITHMS)"
                )
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
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    scenarios: ScenarioSettings = Field(default_factory=ScenarioSettings)
    authn: AuthnSettings = Field(default_factory=AuthnSettings)

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
        if self.rag.api_key:
            value["rag"]["api_key"] = self.rag.api_key.redacted()
        if self.observability.public_key:
            value["observability"]["public_key"] = (
                self.observability.public_key.redacted()
            )
        if self.observability.secret_key:
            value["observability"]["secret_key"] = (
                self.observability.secret_key.redacted()
            )
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
