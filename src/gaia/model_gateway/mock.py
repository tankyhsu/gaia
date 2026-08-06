"""Framework-owned deterministic mock `ModelProvider`.

This is the instance the built-in `model-mock` Starter registers (see
`gaia.starters.builtin`). It exists so declarative applications that only declare
`starters: [model-mock, ...]` get a real, working `ModelProvider` without having to
hand-write one -- previously the Starter only registered a placeholder marker dict.

It must stay generic: no domain-specific parsing. Reference applications under
`examples/` are free to ship their own mock provider that parses application-specific
intent out of free text; that is application logic, and the framework must not depend on
`examples/` (see
`tests/architecture/test_boundaries.py::test_framework_never_imports_reference_applications`).
Instead, this provider fills the requested `output_schema` generically from its field
types: required `str` fields are populated from the last user message, other required
scalar/collection fields get a deterministic type-appropriate placeholder, and fields
with a default (including `Optional` fields defaulting to `None`) are left at that
default. Same input always yields the same output.
"""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from gaia.contracts.models import ModelEndpointProfile, ModelHealth
from gaia.spi.model import (
    ModelCallContext,
    ModelMessage,
    ModelResult,
    ModelStreamChunk,
    ModelUsage,
)


class DeterministicMockProvider:
    """A dependency-free, deterministic `ModelProvider` for declarative applications."""

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        return ModelHealth(
            provider_id=profile.provider_id,
            model_id=profile.model_id,
            healthy=True,
            capabilities=profile.capabilities,
            checked_at=datetime.now(UTC),
        )

    async def generate_structured(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        output_schema: type[BaseModel],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> ModelResult:
        del timeout_seconds, context
        text = messages[-1].content if messages else ""
        validated = output_schema.model_validate(_deterministic_payload(output_schema, text))
        return ModelResult(
            output=validated.model_dump(mode="json"),
            model_id=profile.model_id,
            usage=_usage_for(messages, text),
        )

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        del timeout_seconds, context
        if not profile.capabilities.streaming:
            raise ValueError("MODEL_STREAMING_NOT_SUPPORTED")
        text = messages[-1].content if messages else ""
        yield ModelStreamChunk(
            delta=text,
            model_id=profile.model_id,
            finish_reason="stop",
            usage=_usage_for(messages, text),
        )


def _usage_for(messages: list[ModelMessage], text: str) -> ModelUsage:
    input_tokens = sum(len(message.content.split()) for message in messages)
    output_tokens = len(text.split())
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def _deterministic_payload(schema: type[BaseModel], text: str) -> dict[str, Any]:
    """Build a schema-shaped payload deterministically from `text`.

    Only fields pydantic considers *required* (no default, no default_factory) are
    filled in; everything else is left for pydantic's own default (which is `None`
    for the common `X | None = None` optional-field pattern), matching the "leave
    optionals as None" contract.
    """
    payload: dict[str, Any] = {}
    for name, field_info in schema.model_fields.items():
        if not field_info.is_required():
            continue
        payload[name] = _placeholder_for(field_info.annotation, text)
    return payload


def _placeholder_for(annotation: Any, text: str) -> Any:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        candidates = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _placeholder_for(candidates[0], text) if candidates else None
    if annotation is str:
        return text
    if annotation is int:
        return len(text)
    if annotation is float:
        return float(len(text))
    if annotation is bool:
        return bool(text.strip())
    if origin in (list, set, frozenset, tuple):
        return []
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _deterministic_payload(annotation, text)
    return None
