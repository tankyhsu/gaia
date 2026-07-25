import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2] / "src" / "gaia"
PROJECT_ROOT = Path(__file__).parents[2]
WEB_ROOT = PROJECT_ROOT / "apps" / "web" / "src"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}


def python_files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.py"))


def test_contracts_and_sdk_do_not_depend_on_framework_implementations() -> None:
    forbidden_prefixes = (
        "gaia.application",
        "gaia.api",
        "gaia.capabilities",
        "gaia.integrations",
        "gaia.persistence",
        "gaia.runtime",
        "gaia.starters",
    )
    for folder in (ROOT / "contracts", ROOT / "sdk"):
        for path in folder.glob("*.py"):
            dependencies = imports(path)
            assert not any(name.startswith(forbidden_prefixes) for name in dependencies), (
                f"{path.relative_to(ROOT)} depends on a framework implementation"
            )


def test_generic_runtime_contains_no_customer_business_terms() -> None:
    forbidden = {"售后", "工单", "客服", "保险理赔", "供应链"}
    generic_folders = [ROOT / "contracts", ROOT / "sdk", ROOT / "runtime"]
    text = "\n".join(path.read_text() for folder in generic_folders for path in folder.glob("*.py"))
    assert not forbidden.intersection(text)


def test_framework_never_imports_reference_applications() -> None:
    forbidden_prefixes = ("examples", "gaia.examples")
    for path in python_files(ROOT):
        dependencies = imports(path)
        assert not any(dependency.startswith(forbidden_prefixes) for dependency in dependencies), (
            f"{path.relative_to(ROOT)} imports a reference application"
        )


def test_runtime_never_imports_integrations_or_capability_packs() -> None:
    forbidden_prefixes = (
        "gaia.integrations",
        "gaia.capabilities",
        "langgraph",
    )
    for path in python_files(ROOT / "runtime"):
        dependencies = imports(path)
        assert not any(dependency.startswith(forbidden_prefixes) for dependency in dependencies), (
            f"{path.relative_to(ROOT)} imports an application implementation"
        )


def test_framework_source_has_no_reference_application_constants() -> None:
    forbidden = {"controlled-task", "controlled_task", "res-001", "org-alpha"}
    for path in python_files(ROOT):
        text = path.read_text()
        assert not any(value in text for value in forbidden), (
            f"{path.relative_to(ROOT)} contains a reference application constant"
        )


def test_integrations_do_not_own_application_or_runtime_policy() -> None:
    forbidden_prefixes = (
        "gaia.application",
        "gaia.capabilities",
        "gaia.runtime",
        "gaia.starters",
    )
    for path in python_files(ROOT / "integrations"):
        dependencies = imports(path)
        assert not any(dependency.startswith(forbidden_prefixes) for dependency in dependencies), (
            f"{path.relative_to(ROOT)} crosses the integration boundary"
        )


def test_capabilities_do_not_depend_on_application_or_starters() -> None:
    forbidden_prefixes = ("gaia.application", "gaia.starters", "gaia.api")
    for path in python_files(ROOT / "capabilities"):
        dependencies = imports(path)
        assert not any(dependency.startswith(forbidden_prefixes) for dependency in dependencies), (
            f"{path.relative_to(ROOT)} crosses the capability boundary"
        )


def test_dev_compose_contains_only_optional_infrastructure() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "infra" / "dev" / "compose.yaml").read_text()
    )

    assert set(compose["services"]) == {"postgres", "redis"}
    assert {"gaia", "web", "docs"}.isdisjoint(compose["services"])


def test_dev_console_has_no_reference_application_constants() -> None:
    forbidden = {"controlled-task", "controlled_task", "res-001", "org-alpha"}
    for path in sorted(WEB_ROOT.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text()
        assert not any(value in text for value in forbidden), (
            f"{path.relative_to(WEB_ROOT)} contains a reference application constant"
        )
