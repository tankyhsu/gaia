"""Minimal OpenAI-compatible structured-output provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

from gaia.contracts.models import ErrorCode, ModelEndpointProfile, ModelHealth
from gaia.sdk.model import (
    ModelCallContext,
    ModelMessage,
    ModelResult,
    ModelStreamChunk,
    ModelUsage,
)


class OpenAICompatibleProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def health(self, profile: ModelEndpointProfile) -> ModelHealth:
        if not profile.base_url:
            return ModelHealth(
                provider_id=profile.provider_id,
                model_id=profile.model_id,
                healthy=False,
                capabilities=profile.capabilities,
                checked_at=datetime.now(UTC),
                error_code=ErrorCode.MODEL_UNAVAILABLE,
            )
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
        del context
        if not profile.base_url:
            raise RuntimeError(ErrorCode.MODEL_UNAVAILABLE)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {
            "model": profile.model_id,
            "messages": [message.model_dump() for message in messages],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(base_url=profile.base_url, timeout=timeout_seconds) as client:
            response = await client.post("/chat/completions", json=body, headers=headers)
            response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        validated = output_schema.model_validate_json(content)
        usage_payload = payload.get("usage")
        usage = (
            None
            if not isinstance(usage_payload, dict)
            else ModelUsage(
                input_tokens=int(usage_payload.get("prompt_tokens", 0)),
                output_tokens=int(usage_payload.get("completion_tokens", 0)),
                total_tokens=int(
                    usage_payload.get(
                        "total_tokens",
                        int(usage_payload.get("prompt_tokens", 0))
                        + int(usage_payload.get("completion_tokens", 0)),
                    )
                ),
            )
        )
        return ModelResult(
            output=validated.model_dump(mode="json"),
            model_id=profile.model_id,
            provider_response_id=payload.get("id"),
            usage=usage,
        )

    async def generate_stream(
        self,
        *,
        profile: ModelEndpointProfile,
        messages: list[ModelMessage],
        timeout_seconds: int,
        context: ModelCallContext | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        del context
        if not profile.base_url:
            raise RuntimeError(ErrorCode.MODEL_UNAVAILABLE)
        if not profile.capabilities.streaming:
            raise ValueError("MODEL_STREAMING_NOT_SUPPORTED")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {
            "model": profile.model_id,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with httpx.AsyncClient(base_url=profile.base_url, timeout=timeout_seconds) as client:
            async with client.stream(
                "POST",
                "/chat/completions",
                json=body,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if not data or data == "[DONE]":
                        continue
                    payload = json.loads(data)
                    choices = payload.get("choices") or []
                    choice = choices[0] if choices else {}
                    delta = choice.get("delta") or {}
                    usage_payload = payload.get("usage")
                    yield ModelStreamChunk(
                        delta=str(delta.get("content") or ""),
                        model_id=str(payload.get("model") or profile.model_id),
                        provider_response_id=payload.get("id"),
                        finish_reason=choice.get("finish_reason"),
                        usage=_usage(usage_payload),
                    )


def _usage(payload: object) -> ModelUsage | None:
    if not isinstance(payload, dict):
        return None
    input_tokens = int(payload.get("prompt_tokens", 0))
    output_tokens = int(payload.get("completion_tokens", 0))
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=int(payload.get("total_tokens", input_tokens + output_tokens)),
    )
