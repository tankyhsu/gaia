"""Immutable prompt artifacts and the provider boundary."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gaia.contracts.models import RunMode

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PromptRef(BaseModel):
    """An exact immutable prompt version requested by application code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str
    version: str | None = None
    environment: RunMode | None = None
    experiment: str | None = None

    @model_validator(mode="after")
    def valid_selector(self) -> PromptRef:
        if _IDENTIFIER.fullmatch(self.prompt_id) is None:
            raise ValueError("prompt_id contains unsupported characters")
        selectors = (self.version, self.environment, self.experiment)
        if sum(item is not None for item in selectors) != 1:
            raise ValueError("exactly one prompt selector is required")
        if self.version is not None and _IDENTIFIER.fullmatch(self.version) is None:
            raise ValueError("prompt version contains unsupported characters")
        if self.experiment is not None and _IDENTIFIER.fullmatch(self.experiment) is None:
            raise ValueError("prompt experiment contains unsupported characters")
        return self

    @property
    def exact(self) -> bool:
        return self.version is not None


class PromptMessage(BaseModel):
    """One provider-neutral chat message template."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)


class PromptArtifact(BaseModel):
    """A versioned prompt whose content hash makes mutation detectable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str
    version: str
    content_hash: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    messages: tuple[PromptMessage, ...] = Field(min_length=1)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> PromptArtifact:
        PromptRef(prompt_id=self.prompt_id, version=self.version)
        calculated = self.calculate_hash()
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("prompt content_hash does not match artifact content")
        object.__setattr__(self, "content_hash", calculated)
        return self

    def calculate_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def ref(self) -> PromptRef:
        return PromptRef(prompt_id=self.prompt_id, version=self.version)

    @property
    def version_id(self) -> str:
        return f"{self.prompt_id}:{self.version}@{self.content_hash}"


class PromptLifecycleStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PUBLISHED = "published"
    RETIRED = "retired"


class PromptValidation(BaseModel):
    """Versioned quality evidence required before publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    dataset_id: str
    dataset_version: str
    report_id: str
    gate_ids: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class PromptVersion(BaseModel):
    """Registry projection for one immutable artifact version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: PromptArtifact
    status: PromptLifecycleStatus
    validation: PromptValidation | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class PromptRelease(BaseModel):
    """The current immutable version selected for one environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str
    environment: RunMode
    version: str
    content_hash: str
    updated_by: str
    updated_at: datetime

    @property
    def artifact_version_id(self) -> str:
        return f"{self.prompt_id}:{self.version}@{self.content_hash}"


@runtime_checkable
class PromptProvider(Protocol):
    """Resolve a prompt selector to one immutable artifact."""

    async def resolve(self, ref: PromptRef) -> PromptArtifact: ...


@runtime_checkable
class PromptRegistry(PromptProvider, Protocol):
    """Lifecycle operations implemented by mutable registry providers."""

    async def import_draft(self, artifact: PromptArtifact, *, actor: str) -> PromptVersion: ...

    async def validate(
        self,
        ref: PromptRef,
        evidence: PromptValidation,
        *,
        actor: str,
    ) -> PromptVersion: ...

    async def publish(
        self,
        ref: PromptRef,
        environment: RunMode,
        *,
        actor: str,
    ) -> PromptRelease: ...

    async def retire(self, ref: PromptRef, *, actor: str) -> PromptVersion: ...

    async def rollback(
        self,
        prompt_id: str,
        environment: RunMode,
        target_version: str,
        *,
        actor: str,
    ) -> PromptRelease: ...
