"""Application-facing domain event and publisher contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    topic: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    event_type: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    key: str | None = Field(default=None, max_length=256)
    payload: dict[str, Any]
    headers: dict[str, str] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


class EventPublisher(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...
