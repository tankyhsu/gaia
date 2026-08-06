"""Opt-in Prompt workspace routes with provider-aware access."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from gaia.application import GaiaApplication
from gaia.contracts.models import RunMode, UserIdentity
from gaia.integrations.prompt_files import FilePromptProvider
from gaia.integrations.prompt_postgres import (
    PostgresPromptRegistry,
    PromptRegistryConflict,
    PromptRegistryNotFound,
)
from gaia.spi.prompt import PromptArtifact, PromptRef

# Resolves the caller identity for one request: `(identity, None)` when the
# request may proceed (`identity` is `None` for a trusted-service caller with
# no end-user identity), or `(None, response)` with a 401 `JSONResponse` when
# authentication failed. The Prompt workspace is not scoped to a single end
# user's resources, so `identity` is accepted for symmetry with the rest of
# the API surface (F1: no protected endpoint should discard it) but is not
# itself consulted for an ownership decision here.
Authorization = Callable[[Request], Awaitable[tuple[UserIdentity | None, JSONResponse | None]]]


class DevtoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptPublishRequest(DevtoolRequest):
    environment: RunMode


class PromptRollbackRequest(DevtoolRequest):
    environment: RunMode
    target_version: str


class FilePromptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str
    version: str
    content_hash: str
    relative_path: str


class PromptWorkspaceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["disabled", "file", "postgres"]
    access: Literal["unavailable", "read_only", "read_write"]
    component_id: str | None = None
    root: str | None = None
    artifacts: tuple[FilePromptSummary, ...] = ()


def create_prompt_devtools_router(
    authorize: Authorization,
    application: GaiaApplication,
) -> APIRouter:
    router = APIRouter(prefix="/devtools/prompts", tags=["devtools-prompts"])

    def registry_provider() -> PostgresPromptRegistry:
        try:
            return cast(
                PostgresPromptRegistry,
                application.get_component("prompt-postgres", expected=PostgresPromptRegistry),
            )
        except TypeError:
            raise HTTPException(status_code=409, detail="PROMPT_REGISTRY_UNAVAILABLE") from None

    @router.get("", response_model=PromptWorkspaceStatus)
    async def workspace_status(
        request: Request,
    ) -> PromptWorkspaceStatus | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        provider = application.config.prompt.provider
        if provider == "disabled":
            return PromptWorkspaceStatus(
                provider=provider,
                access="unavailable",
            )

        component_id = f"prompt-{provider}"
        if provider == "file":
            try:
                file_component = application.get_component(
                    component_id, expected=FilePromptProvider
                )
            except TypeError:
                raise HTTPException(
                    status_code=409,
                    detail="PROMPT_FILE_PROVIDER_UNAVAILABLE",
                ) from None
            artifacts = await file_component.list_artifacts()
            return PromptWorkspaceStatus(
                provider=provider,
                access="read_only",
                component_id=component_id,
                root=str(file_component.root),
                artifacts=tuple(
                    FilePromptSummary(
                        prompt_id=artifact.prompt_id,
                        version=artifact.version,
                        content_hash=artifact.content_hash,
                        relative_path=f"{artifact.prompt_id}/{artifact.version}.yaml",
                    )
                    for artifact in artifacts
                ),
            )

        try:
            application.get_component(component_id, expected=PostgresPromptRegistry)
        except TypeError:
            raise HTTPException(
                status_code=409,
                detail="PROMPT_REGISTRY_UNAVAILABLE",
            ) from None
        return PromptWorkspaceStatus(
            provider=provider,
            access="read_write",
            component_id=component_id,
        )

    @router.get("/{prompt_id}", response_model=None)
    async def inspect_prompt(request: Request, prompt_id: str) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        registry = registry_provider()
        versions = await registry.versions(prompt_id)
        releases = await registry.releases(prompt_id)
        return {
            "prompt_id": prompt_id,
            "versions": [item.model_dump(mode="json") for item in versions],
            "releases": [item.model_dump(mode="json") for item in releases],
        }

    @router.post("/import", status_code=201, response_model=None)
    async def import_prompt(
        request: Request,
        artifact: PromptArtifact,
        actor: str = Header(alias="X-Gaia-Actor", min_length=1),
    ) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        try:
            version = await registry_provider().import_draft(artifact, actor=actor)
        except PromptRegistryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return version.model_dump(mode="json")

    @router.post("/{prompt_id}/{version}/publish", response_model=None)
    async def publish_prompt(
        request: Request,
        prompt_id: str,
        version: str,
        body: PromptPublishRequest,
        actor: str = Header(alias="X-Gaia-Actor", min_length=1),
    ) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        try:
            release = await registry_provider().publish(
                PromptRef(prompt_id=prompt_id, version=version),
                body.environment,
                actor=actor,
            )
        except PromptRegistryNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PromptRegistryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return release.model_dump(mode="json")

    @router.post("/{prompt_id}/rollback", response_model=None)
    async def rollback_prompt(
        request: Request,
        prompt_id: str,
        body: PromptRollbackRequest,
        actor: str = Header(alias="X-Gaia-Actor", min_length=1),
    ) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        try:
            release = await registry_provider().rollback(
                prompt_id,
                body.environment,
                body.target_version,
                actor=actor,
            )
        except PromptRegistryNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PromptRegistryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return release.model_dump(mode="json")

    return router
