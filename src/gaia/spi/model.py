"""Public model provider protocol and model result declarations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gaia.contracts.models import ModelEndpointProfile, ModelHealth


class ModelMessage(BaseModel):
    role: str
    content: str


class ModelCallContext(BaseModel):
    """Correlation metadata supplied by the application without prompt content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    scenario_id: str
    prompt_version: str
    prompt_content_hash: str | None = None


class ModelUsage(BaseModel):
    """Provider-neutral token and optional cost evidence."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    currency: str | None = None

    @model_validator(mode="after")
    def total_matches_parts(self) -> ModelUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        if (self.estimated_cost is None) != (self.currency is None):
            raise ValueError("estimated_cost and currency must be provided together")
        return self


class ModelResult(BaseModel):
    output: dict[str, object]
    model_id: str
    provider_response_id: str | None = None
    usage: ModelUsage | None = None
    first_token_latency_ms: int | None = Field(default=None, ge=0)


class ModelStreamChunk(BaseModel):
    """One provider-neutral text delta from a streaming model call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delta: str = ""
    model_id: str
    provider_response_id: str | None = None
    finish_reason: str | None = None
    usage: ModelUsage | None = None


class ModelProvider(Protocol):
    async def health(self, profile: ModelEndpointProfile) -> ModelHealth: ...

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult: ...

    def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]: ...
