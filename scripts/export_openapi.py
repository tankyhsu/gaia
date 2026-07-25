"""Export the public Gaia OpenAPI document from the reference application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from examples.controlled_task.app import create_app

ROOT = Path(__file__).parents[1]
PUBLIC_ROUTES = {
    "/health/live",
    "/health/ready",
    "/actuator/info",
    "/actuator/health",
}


def build_schema() -> dict[str, Any]:
    schema = cast(dict[str, Any], create_app().openapi())
    schema["info"]["license"] = {
        "name": "Proprietary",
        "identifier": "LicenseRef-Proprietary",
    }
    schema["servers"] = [{"url": "/", "description": "Gaia application on the current host"}]
    schema["security"] = [{"ApiKeyAuth": []}]
    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Gaia-Api-Key",
        }
    }
    for path, path_item in schema["paths"].items():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            if path in PUBLIC_ROUTES:
                operation["security"] = []
            else:
                operation["responses"].setdefault(
                    "401",
                    {
                        "description": "Unauthorized",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                            }
                        },
                    },
                )
    return schema


if __name__ == "__main__":
    target = ROOT / "specs" / "openapi.json"
    target.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
