import json
from pathlib import Path

from gaia.api.app import create_app


def test_fastapi_exposes_every_public_p0_operation() -> None:
    source = json.loads((Path(__file__).parents[2] / "specs" / "openapi.json").read_text())
    expected = {
        (method.upper(), path)
        for path, operations in source["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    generated = create_app().openapi()
    actual = {
        (method.upper(), path)
        for path, operations in generated["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert expected <= actual


def test_openapi_source_is_valid_json() -> None:
    source = json.loads((Path(__file__).parents[2] / "specs" / "openapi.json").read_text())
    assert source["openapi"] == "3.1.0"
    assert source["info"]["title"] == "Gaia Application Framework API"
    assert source["info"]["license"]["identifier"] == "LicenseRef-Proprietary"
    assert source["servers"] == [
        {"url": "/", "description": "Gaia application on the current host"}
    ]


def test_openapi_only_exposes_schemas_used_by_public_http_contract() -> None:
    source = json.loads((Path(__file__).parents[2] / "specs" / "openapi.json").read_text())
    internal_schemas = {
        "ExecutionPolicy",
        "ContextEnvelope",
        "ToolDefinition",
        "ToolResult",
        "SideEffectCommand",
        "ModelEndpointProfile",
    }
    assert internal_schemas.isdisjoint(source["components"]["schemas"])

    for path, path_item in source["paths"].items():
        for operation in path_item.values():
            if operation.get("security", source["security"]):
                assert "401" in operation["responses"], path
