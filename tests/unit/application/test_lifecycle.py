from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType

import pytest

from gaia.application import ApplicationState, GaiaApplication
from gaia.components import (
    ComponentDescriptor,
    ComponentKind,
    ComponentRegistry,
    ComponentScope,
)
from gaia.config import GaiaApplicationConfig
from gaia.spi.prompt import PromptRef

# A deliberately simplified PEP 440 shape check (release segment, optional
# pre/post/dev segments, optional local version) -- enough to catch "this is
# not a version string at all" without depending on the `packaging` library.
_PEP440_LIKE = re.compile(
    r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$"
)


def resource_descriptor(
    identifier: str,
    *,
    kind: ComponentKind,
    depends_on: tuple[str, ...] = (),
) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=identifier,
        kind=kind,
        implementation="tests.resource",
        starter_id="tests",
        profile="mock",
        depends_on=depends_on,
        scope=ComponentScope.APPLICATION,
        reason="test",
    )


async def test_failed_resource_entry_releases_prior_resources_in_reverse() -> None:
    events: list[str] = []
    registry = ComponentRegistry()

    @asynccontextmanager
    async def first_resource() -> AsyncIterator[str]:
        events.append("enter:first")
        try:
            yield "first-value"
        finally:
            events.append("exit:first")

    @asynccontextmanager
    async def failing_resource(first: object) -> AsyncIterator[str]:
        assert first == "first-value"
        events.append("enter:second")
        raise RuntimeError("boom")
        yield "unreachable"

    registry.register_resource(
        resource_descriptor("first", kind=ComponentKind.TOOL),
        lambda _components: first_resource(),
    )
    registry.register_resource(
        resource_descriptor(
            "second",
            kind=ComponentKind.CONTEXT,
            depends_on=("first",),
        ),
        lambda components: failing_resource(components["first"]),
    )

    application = GaiaApplication(GaiaApplicationConfig(), registry)
    with pytest.raises(RuntimeError, match="boom"):
        await application.start()

    assert application.state == ApplicationState.FAILED
    assert events == ["enter:first", "enter:second", "exit:first"]


async def test_configure_has_no_resource_side_effects_and_lifespan_owns_scope() -> None:
    events: list[str] = []
    registry = ComponentRegistry()

    @asynccontextmanager
    async def managed_resource() -> AsyncIterator[str]:
        events.append("enter")
        try:
            yield "ready"
        finally:
            events.append("exit")

    registry.register_resource(
        resource_descriptor("managed", kind=ComponentKind.TOOL),
        lambda _components: managed_resource(),
    )
    application = GaiaApplication(GaiaApplicationConfig(), registry)

    configured = await application.configure()

    assert configured.components == {}
    assert events == []
    with pytest.raises(RuntimeError, match="APPLICATION_NOT_STARTED"):
        application.get_component("managed")

    async with application.lifespan() as started:
        assert application.state == ApplicationState.STARTED
        assert started.components["managed"] == "ready"
        assert application.get_component("managed") == "ready"
        with pytest.raises(KeyError, match="COMPONENT_NOT_FOUND:missing"):
            application.get_component("missing")
        assert events == ["enter"]

    assert application.state == ApplicationState.STOPPED
    with pytest.raises(RuntimeError, match="APPLICATION_NOT_STARTED"):
        application.get_component("managed")
    assert application.actuator_snapshot().config
    assert (await application.configure()).components == {}
    assert events == ["enter", "exit"]


async def test_get_component_expected_type_matches_and_mismatches() -> None:
    """E1: `expected` asserts the port a caller genuinely requires."""

    class Widget:
        pass

    registry = ComponentRegistry()

    @asynccontextmanager
    async def widget_resource() -> AsyncIterator[Widget]:
        yield Widget()

    registry.register_resource(
        resource_descriptor("widget", kind=ComponentKind.TOOL),
        lambda _components: widget_resource(),
    )
    application = GaiaApplication(GaiaApplicationConfig(), registry)

    async with application.lifespan():
        # Correct type: passes through unchanged.
        widget = application.get_component("widget", expected=Widget)
        assert isinstance(widget, Widget)
        # No `expected`: unchanged legacy behaviour, no type assertion at all.
        assert isinstance(application.get_component("widget"), Widget)
        # Wrong type: a catalogued TypeError, not a silently-wrong instance.
        with pytest.raises(TypeError, match="COMPONENT_TYPE_MISMATCH:widget"):
            application.get_component("widget", expected=str)


async def test_actuator_snapshot_uses_redacted_config_and_context() -> None:
    application = GaiaApplication(GaiaApplicationConfig())
    await application.configure()
    snapshot = application.actuator_snapshot()
    assert snapshot.application_name == "gaia-app"
    assert snapshot.state == "configured"
    # E2: framework_version comes from installed package metadata now, not a
    # hand-typed literal -- assert the semantic property (non-empty, PEP
    # 440 shaped) instead of a specific value that would drift from
    # pyproject.toml.
    assert snapshot.framework_version
    assert _PEP440_LIKE.match(snapshot.framework_version)
    assert snapshot.conditions
    assert snapshot.config["model"]["api_key"] is None


def test_framework_version_falls_back_when_package_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2: `_framework_version` reads installed package metadata, not a literal,

    and degrades to a clearly-marked dev sentinel rather than crashing when
    the package isn't installed (e.g. a bare source checkout).
    """

    from importlib.metadata import PackageNotFoundError

    import gaia.application.core as core_module

    def _raise(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(core_module, "version", _raise)

    assert core_module._framework_version() == "0.0.0+dev"


async def test_from_config_autoconfigures_framework_components(tmp_path: Path) -> None:
    config_path = tmp_path / "gaia.yaml"
    config_path.write_text("gaia:\n  application: {name: sample, version: 1.0.0}\n")
    context = await GaiaApplication.from_config(config_path).configure()
    kinds = {item.kind.value for item in context.descriptors}
    assert {"model", "workflow", "context", "policy", "persistence"} <= kinds
    assert context.auto_configuration_report is not None
    assert len(context.component_graph_hash) == 64
    assert isinstance(context.config, MappingProxyType)
    with pytest.raises(TypeError):
        context.config["profile"] = "changed"  # type: ignore[index]


async def test_file_prompt_root_is_relative_to_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application_root = tmp_path / "application"
    prompt_dir = application_root / "prompts" / "hello"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "1.0.0.yaml").write_text(
        "prompt_id: hello\nversion: 1.0.0\nmessages:\n  - role: system\n    content: Hello.\n"
    )
    config_path = application_root / "gaia.yaml"
    config_path.write_text("gaia:\n  prompt: {provider: file, root: prompts}\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    application = GaiaApplication.from_config(config_path)

    assert application.config.prompt.root == str((application_root / "prompts").resolve())
    async with application.lifespan():
        provider = application.get_component("prompt-file")
        artifact = await provider.resolve(PromptRef(prompt_id="hello", version="1.0.0"))
    assert artifact.prompt_id == "hello"


async def test_explicit_component_does_not_disable_other_auto_configuration() -> None:
    registry = ComponentRegistry()
    registry.register(
        ComponentDescriptor(
            component_id="custom-model",
            kind=ComponentKind.MODEL,
            implementation="tests.CustomModel",
            starter_id="application",
            profile="mock",
            reason="explicit",
        ),
        lambda _components: object(),
    )
    application = GaiaApplication(GaiaApplicationConfig(), registry)

    configured = await application.configure()
    kinds = {item.kind for item in configured.descriptors}
    assert ComponentKind.MODEL in kinds
    assert ComponentKind.WORKFLOW in kinds
    assert ComponentKind.CONTEXT in kinds
    assert ComponentKind.POLICY in kinds
    assert ComponentKind.PERSISTENCE in kinds
    assert all(item.component_id != "model-default" for item in configured.descriptors)

    async with application.lifespan() as started:
        assert "custom-model" in started.components
        assert "model-default" not in started.components
