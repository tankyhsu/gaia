"""Pure read-only models shared by future Actuator adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from gaia.components.core import ComponentDescriptor, ComponentHealth


class ActuatorCondition(BaseModel):
    model_config = ConfigDict(frozen=True)
    starter_id: str
    matched: bool
    reasons: tuple[str, ...]


class ActuatorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    application_name: str
    application_version: str
    framework_version: str
    profile: str
    config_hash: str
    component_graph_hash: str
    components: tuple[ComponentDescriptor, ...]
    state: str
    started_at: datetime | None
    config: dict[str, Any]
    origins: dict[str, str]
    conditions: tuple[ActuatorCondition, ...]


class ActuatorInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    application_name: str
    application_version: str
    framework_version: str
    profile: str
    state: str
    config_hash: str
    component_graph_hash: str
    started_at: datetime | None
    devtools_enabled: bool = False


class ComponentHealthEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    component_id: str
    required: bool = True
    health: ComponentHealth


class ActuatorHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    components: tuple[ComponentHealthEntry, ...]


class ActuatorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_hash: str
    config: dict[str, Any]
    origins: dict[str, str]
