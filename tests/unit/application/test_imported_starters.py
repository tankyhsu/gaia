from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from gaia.application import GaiaApplication
from gaia.components.core import ComponentDescriptor, ComponentKind, ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.starters import OnProfile, StarterDescriptor


class CustomStarter:
    descriptor = StarterDescriptor("custom-starter", "1.0.0", ("custom",))

    def defaults(self) -> dict[str, object]:
        return {"application": {"name": "from-custom-starter"}}

    def conditions(self) -> list[OnProfile]:
        return [OnProfile("mock")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        registry.register(
            ComponentDescriptor(
                component_id="custom-component",
                kind=ComponentKind.CONTEXT,
                implementation="custom",
                starter_id="custom-starter",
                profile=config.profile,
                reason="custom",
            ),
            lambda _components: {"name": config.application.name},
        )


@pytest.mark.asyncio
async def test_imported_starter_is_loaded_defaults_then_configured(tmp_path: Path) -> None:
    module = ModuleType("temporary_custom_starter")
    module.starter = CustomStarter()
    sys.modules[module.__name__] = module
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  starters:\n    - import: temporary_custom_starter:starter\n")
    try:
        context = await GaiaApplication.from_config(config).configure()
    finally:
        del sys.modules[module.__name__]

    assert context.config["application"]["name"] == "from-custom-starter"
    assert context.config["starters"] == ({"import": "temporary_custom_starter:starter"},)
    assert [item.component_id for item in context.descriptors] == ["custom-component"]


def test_invalid_import_has_stable_error_code(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  starters:\n    - import: missing_module:starter\n")

    with pytest.raises(ValueError, match="CONFIG_STARTER_IMPORT_ERROR:missing_module:starter"):
        GaiaApplication.from_config(config)
