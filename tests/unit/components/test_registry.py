import pytest

from gaia.components import ComponentDescriptor, ComponentKind, ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.starters import BUILTIN_STARTERS, AutoConfigurator


def descriptor(identifier: str, *, depends_on: tuple[str, ...] = ()) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=identifier,
        kind=ComponentKind.TOOL,
        implementation="x",
        starter_id="s",
        profile="mock",
        reason="test",
        depends_on=depends_on,
    )


def test_registry_detects_duplicate_missing_and_cycle() -> None:
    registry = ComponentRegistry()
    registry.register(descriptor("a"), lambda _components: "a")
    with pytest.raises(ValueError, match="DUPLICATE"):
        registry.register(descriptor("a"), lambda _components: "b")
    missing = ComponentRegistry()
    missing.register(descriptor("a", depends_on=("missing",)), lambda _components: "a")
    with pytest.raises(ValueError, match="MISSING"):
        missing.instantiate()
    cycle = ComponentRegistry()
    cycle.register(descriptor("a", depends_on=("b",)), lambda _components: "a")
    cycle.register(descriptor("b", depends_on=("a",)), lambda _components: "b")
    with pytest.raises(ValueError, match="CYCLE"):
        cycle.instantiate()


def test_autoconfiguration_reports_negative_match_and_conflict() -> None:
    config = GaiaApplicationConfig(starters=("model-openai-compatible",))
    _, report = AutoConfigurator(BUILTIN_STARTERS).configure(config)
    assert report.negative[0].starter_id == "model-openai-compatible"


def test_explicit_component_replaces_starter_default() -> None:
    registry = ComponentRegistry()
    registry.register(
        ComponentDescriptor(
            component_id="custom-model",
            kind=ComponentKind.MODEL,
            implementation="custom",
            starter_id="application",
            profile="mock",
            reason="explicit",
        ),
        lambda _components: "custom",
    )
    configured, _ = AutoConfigurator(BUILTIN_STARTERS).configure(
        GaiaApplicationConfig(starters=("model-mock",)), registry
    )
    assert [item.component_id for item in configured.descriptors()] == ["custom-model"]
