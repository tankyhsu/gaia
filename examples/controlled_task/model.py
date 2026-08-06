"""Deterministic controlled-task intent model used by P0."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel

from gaia.contracts.models import ModelEndpointProfile, ModelHealth
from gaia.spi.model import ModelCallContext, ModelMessage, ModelResult

RESOURCE_PATTERN = re.compile(r"res-[0-9]{3}")


class DeterministicMockProvider:
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
        lowered = text.lower()
        resource_match = RESOURCE_PATTERN.search(lowered)
        operation: str | None = None
        target_status: str | None = None
        if "inspect" in lowered or "查看" in text:
            operation = "inspect"
        elif "pause" in lowered or "暂停" in text:
            operation, target_status = "set_status", "paused"
        elif "activate" in lowered or "启用" in text:
            operation, target_status = "set_status", "active"
        elif "set" in lowered and "status" in lowered:
            operation = "set_status"
        reason = None
        for separator in ("because", "因为"):
            if separator in lowered:
                reason = text[lowered.index(separator) + len(separator) :].strip() or None
                break
        payload = {
            "operation": operation,
            "resource_id": resource_match.group(0) if resource_match else None,
            "target_status": target_status,
            "reason": reason,
        }
        validated = output_schema.model_validate(payload)
        return ModelResult(output=validated.model_dump(mode="json"), model_id=profile.model_id)
