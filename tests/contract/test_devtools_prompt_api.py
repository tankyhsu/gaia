from gaia.api.app import create_app


def test_prompt_editing_routes_are_absent_by_default() -> None:
    paths = create_app(enable_devtools=False).openapi()["paths"]

    assert not any(path.startswith("/devtools/prompts") for path in paths)


def test_prompt_editing_routes_require_explicit_devtools_opt_in() -> None:
    paths = create_app(enable_devtools=True).openapi()["paths"]

    assert "/devtools/prompts" in paths
    assert "/devtools/prompts/import" in paths
    assert "/devtools/prompts/{prompt_id}" in paths
    assert "/devtools/prompts/{prompt_id}/{version}/publish" in paths
