"""Read-only Actuator routes backed by GaiaApplication state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gaia.actuator import (
    ActuatorCondition,
    ActuatorConfig,
    ActuatorHealth,
    ActuatorInfo,
    ComponentHealthEntry,
)
from gaia.application import ApplicationState, GaiaApplication
from gaia.components.core import ComponentStatus
from gaia.contracts.models import UserIdentity
from gaia.observability import RuntimeObservabilityService
from gaia.observability.models import RuntimeSummary
from gaia.runtime.contracts import RuntimeEngine

# Resolves the caller identity for one request: `(identity, None)` when the
# request may proceed (`identity` is `None` for a trusted-service caller with
# no end-user identity), or `(None, response)` with a 401 `JSONResponse` when
# authentication failed. Actuator/devtools routes are not scoped to a single
# end user's resources, so `identity` is accepted for symmetry with the rest
# of the API surface (F1: no protected endpoint should discard it) but is not
# itself consulted for an ownership decision here.
Authorization = Callable[[Request], Awaitable[tuple[UserIdentity | None, JSONResponse | None]]]


def create_actuator_router(
    authorize: Authorization,
    *,
    devtools_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/actuator", tags=["actuator"])

    def application(request: Request) -> GaiaApplication:
        return cast(GaiaApplication, request.app.state.gaia_application)

    @router.get("/info", response_model=ActuatorInfo)
    async def info(request: Request) -> ActuatorInfo:
        snapshot = application(request).actuator_snapshot()
        return ActuatorInfo(
            application_name=snapshot.application_name,
            application_version=snapshot.application_version,
            framework_version=snapshot.framework_version,
            profile=snapshot.profile,
            state=snapshot.state,
            config_hash=snapshot.config_hash,
            component_graph_hash=snapshot.component_graph_hash,
            started_at=snapshot.started_at,
            devtools_enabled=devtools_enabled,
        )

    @router.get("/health", response_model=ActuatorHealth)
    async def health(request: Request) -> ActuatorHealth:
        app = application(request)
        snapshot = app.actuator_snapshot()
        components = tuple(
            ComponentHealthEntry(component_id=item.component_id, health=item.health)
            for item in snapshot.components
        )
        failed = any(item.health.status == ComponentStatus.FAILED for item in components)
        status = "UP" if app.state == ApplicationState.STARTED and not failed else "DOWN"
        return ActuatorHealth(status=status, components=components)

    @router.get("/components", response_model=list[dict[str, object]])
    async def components(request: Request) -> list[dict[str, object]] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        return [
            cast(dict[str, object], item.model_dump(mode="json"))
            for item in application(request).actuator_snapshot().components
        ]

    @router.get("/config", response_model=ActuatorConfig)
    async def config(request: Request) -> ActuatorConfig | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        snapshot = application(request).actuator_snapshot()
        return ActuatorConfig(
            config_hash=snapshot.config_hash,
            config=snapshot.config,
            origins=snapshot.origins,
        )

    @router.get("/conditions", response_model=list[ActuatorCondition])
    async def conditions(request: Request) -> list[ActuatorCondition] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        return list(application(request).actuator_snapshot().conditions)

    @router.get("/runtime", response_model=RuntimeSummary)
    async def runtime_summary(
        request: Request,
        window_hours: int = Query(default=24, ge=1, le=168),
        stale_after_seconds: int = Query(default=300, ge=30, le=86400),
    ) -> RuntimeSummary | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        active_runtime = cast(RuntimeEngine | None, request.app.state.runtime)
        return await RuntimeObservabilityService(active_runtime).summary(
            window_hours=window_hours,
            stale_after_seconds=stale_after_seconds,
        )

    return router
