from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from gaia.diagnostics.import_purity import IMPURE_CALLS, PurityFinding, scan_module_purity


@pytest.fixture
def module_on_path(tmp_path: Path) -> Iterator[Path]:
    """Add `tmp_path` to `sys.path` so a `.py` file written there is importable by name.

    `scan_module_purity` never imports the target module itself, but `find_spec` needs the
    module to be *locatable* on `sys.path`, exactly as it would be for a real installed
    scenario module.
    """

    sys.path.insert(0, str(tmp_path))
    try:
        yield tmp_path
    finally:
        sys.path.remove(str(tmp_path))


def _write(module_on_path: Path, name: str, source: str) -> str:
    (module_on_path / f"{name}.py").write_text(textwrap.dedent(source))
    return name


def test_top_level_resolve_secret_is_flagged_with_line_number(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_resolve_secret",
        """
        from gaia.config.secrets import resolve_secret

        VALUE = resolve_secret("db-password")
        """,
    )

    findings = scan_module_purity(module_name)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.module == module_name
    assert finding.symbol == "gaia.config.secrets.resolve_secret"
    assert finding.line == 4
    assert finding.hint


def test_import_httpx_then_top_level_client_is_flagged(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_httpx_client",
        """
        import httpx

        CLIENT = httpx.Client()
        """,
    )

    findings = scan_module_purity(module_name)

    assert [(f.symbol, f.line) for f in findings] == [("httpx.Client", 4)]


def test_from_import_with_alias_is_resolved(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_aliased_async_client",
        """
        from httpx import AsyncClient as C

        CLIENT = C()
        """,
    )

    findings = scan_module_purity(module_name)

    assert [(f.symbol, f.line) for f in findings] == [("httpx.AsyncClient", 4)]


def test_call_inside_function_body_is_not_flagged(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_call_in_function",
        """
        from gaia.config.secrets import resolve_secret


        def build_client() -> str:
            return resolve_secret("db-password")
        """,
    )

    assert scan_module_purity(module_name) == ()


def test_locally_defined_client_class_is_not_flagged(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_local_client_class",
        """
        class Client:
            def __init__(self) -> None:
                self.connected = False


        INSTANCE = Client()
        """,
    )

    assert scan_module_purity(module_name) == ()


def test_arbitrary_object_connect_is_not_flagged(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_obj_connect",
        """
        class Widget:
            def connect(self) -> None:
                pass


        obj = Widget()
        obj.connect()
        """,
    )

    assert scan_module_purity(module_name) == ()


def test_pure_module_returns_no_findings(module_on_path: Path) -> None:
    module_name = _write(
        module_on_path,
        "purity_test_pure_module",
        """
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class Config:
            name: str


        def greet(config: Config) -> str:
            return f"hello {config.name}"
        """,
    )

    assert scan_module_purity(module_name) == ()


def test_module_not_found_returns_no_findings_instead_of_raising() -> None:
    # discover_scenarios is the component responsible for reporting a missing module as a
    # SCENARIO_MODULE_NOT_FOUND error; the purity scan must never raise on this input, and
    # an unresolved module has no source to scan, so it reports nothing.
    assert scan_module_purity("this_module_does_not_exist_anywhere_zzz") == ()


def test_impure_calls_allowlist_has_only_fully_qualified_names() -> None:
    # Guards the "never add a bare name" rule documented on IMPURE_CALLS itself: every
    # entry must contain at least one '.', i.e. be a dotted, resolvable source.
    assert all("." in name for name in IMPURE_CALLS)


def test_purity_finding_is_frozen_and_has_expected_fields() -> None:
    finding = PurityFinding(module="m", line=1, symbol="s", hint="h")
    with pytest.raises(AttributeError):
        finding.line = 2  # type: ignore[misc]
