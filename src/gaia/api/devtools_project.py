"""One-time project initialization endpoints for the local Dev Console."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from gaia.contracts.models import UserIdentity
from gaia.templates import (
    BUSINESS_SCENARIO_TEMPLATES,
    COMPONENT_STARTERS,
    project_files,
    selected_starters,
)

# Resolves the caller identity for one request: `(identity, None)` when the
# request may proceed (`identity` is `None` for a trusted-service caller with
# no end-user identity), or `(None, response)` with a 401 `JSONResponse` when
# authentication failed. Project init is not scoped to a single end user's
# resources, so `identity` is accepted for symmetry with the rest of the API
# surface (F1: no protected endpoint should discard it) but is not itself
# consulted for an ownership decision here.
Authorize = Callable[[Request], Awaitable[tuple[UserIdentity | None, JSONResponse | None]]]
MARKER_PATH = Path(".gaia/init.json")


class ProjectInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    components: tuple[str, ...] = ()


def create_project_devtools_router(
    authorize: Authorize,
    project_root: Path,
) -> APIRouter:
    router = APIRouter(prefix="/devtools/project", tags=["devtools-project"])
    root = project_root.resolve()

    @router.get("/init", response_model=None)
    async def inspect_init(request: Request) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        marker = _read_marker(root)
        selected_template = "knowledge" if marker is None else str(marker["template_id"])
        if selected_template not in BUSINESS_SCENARIO_TEMPLATES:
            selected_template = "knowledge"
        return {
            "available": marker is not None,
            "application_name": "" if marker is None else marker["application_name"],
            "template_id": selected_template,
            "starters": [] if marker is None else marker["starters"],
            "applied": False if marker is None else bool(marker.get("applied", False)),
            "templates": [
                {
                    "id": item.template_id,
                    "name": item.name,
                    "description": item.description,
                    "recommended_components": list(item.recommended_components),
                    "example": (
                        None
                        if item.example is None
                        else {
                            "name": item.example.name,
                            "description": item.example.description,
                            "path": item.example.path,
                        }
                    ),
                }
                for item in BUSINESS_SCENARIO_TEMPLATES.values()
            ],
            "components": [
                {"id": identifier, "name": name, "starter": starter}
                for identifier, (name, starter) in COMPONENT_STARTERS.items()
            ],
        }

    @router.post("/init", response_model=None)
    async def apply_init(
        request: Request,
        body: ProjectInitRequest,
    ) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        marker = _read_marker(root)
        if marker is None:
            return JSONResponse(
                status_code=409,
                content={"code": "PROJECT_INIT_NOT_AVAILABLE", "message": "项目已经完成初始化。"},
            )
        if body.template_id not in BUSINESS_SCENARIO_TEMPLATES:
            return JSONResponse(
                status_code=422,
                content={"code": "UNKNOWN_SCENARIO_TEMPLATE", "message": "未知的场景模板。"},
            )
        unknown = sorted(set(body.components).difference(COMPONENT_STARTERS))
        if unknown:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "UNKNOWN_PROJECT_COMPONENT",
                    "message": f"未知的组件：{', '.join(unknown)}",
                },
            )

        starters = selected_starters(body.template_id, body.components)
        files = project_files(
            str(marker["application_name"]),
            starters,
            template_id=body.template_id,
        )
        old_files = {str(item) for item in marker.get("generated_files", [])}
        _replace_generated_files(root, old_files, files)
        next_marker = json.loads((root / MARKER_PATH).read_text(encoding="utf-8"))
        next_marker["components"] = list(body.components)
        next_marker["applied"] = True
        (root / MARKER_PATH).write_text(
            json.dumps(next_marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "applied": True,
            "template_id": body.template_id,
            "components": list(body.components),
            "starters": list(starters),
            "restart_required": True,
        }

    @router.post("/init/complete", response_model=None)
    async def complete_init(request: Request) -> dict[str, object] | JSONResponse:
        _, unauthorized = await authorize(request)
        if unauthorized:
            return unauthorized
        marker = _read_marker(root)
        if marker is None:
            return {"completed": True}
        if not marker.get("applied"):
            return JSONResponse(
                status_code=409,
                content={"code": "PROJECT_INIT_NOT_APPLIED", "message": "请先应用场景和组件选择。"},
            )
        (root / MARKER_PATH).unlink()
        marker_parent = root / MARKER_PATH.parent
        if marker_parent.exists() and not any(marker_parent.iterdir()):
            marker_parent.rmdir()
        return {"completed": True}

    return router


def _read_marker(root: Path) -> dict[str, Any] | None:
    path = root / MARKER_PATH
    if not path.is_file():
        return None
    value = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if value.get("schema_version") != 1:
        raise ValueError("PROJECT_INIT_MARKER_VERSION_UNSUPPORTED")
    return value


def _replace_generated_files(
    root: Path,
    old_files: set[str],
    files: dict[str, str],
) -> None:
    new_files = set(files)
    for relative in sorted(old_files.difference(new_files), reverse=True):
        target = _project_path(root, relative)
        if target.is_file():
            target.unlink()
    for relative, contents in files.items():
        target = _project_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")


def _project_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("PROJECT_INIT_PATH_OUTSIDE_ROOT")
    return target
