import ast
import importlib.util
import tomllib
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


def test_contracts_and_spi_do_not_depend_on_framework_implementations() -> None:
    forbidden_prefixes = (
        "gaia._authoring",
        "gaia.application",
        "gaia.api",
        "gaia.capabilities",
        "gaia.integrations",
        "gaia.persistence",
        "gaia.runtime",
        "gaia.starters",
    )
    for folder in (ROOT / "contracts", ROOT / "spi"):
        for path in folder.glob("*.py"):
            dependencies = imports(path)
            assert not any(name.startswith(forbidden_prefixes) for name in dependencies), (
                f"{path.relative_to(ROOT)} depends on a framework implementation"
            )


def test_generic_runtime_contains_no_customer_business_terms() -> None:
    forbidden = {"售后", "工单", "客服", "保险理赔", "供应链"}
    generic_folders = [ROOT / "_authoring", ROOT / "contracts", ROOT / "spi", ROOT / "runtime"]
    text = "\n".join(path.read_text() for folder in generic_folders for path in folder.glob("*.py"))
    assert not forbidden.intersection(text)


def test_spi_contains_no_concrete_integrations() -> None:
    allowed_bases = {"BaseModel", "Exception", "Protocol", "StrEnum"}
    for path in python_files(ROOT / "spi"):
        tree = ast.parse(path.read_text())
        for node in (item for item in ast.walk(tree) if isinstance(item, ast.ClassDef)):
            bases = {
                base.id
                for base in node.bases
                if isinstance(base, ast.Name)
            }
            decorators = {
                decorator.func.id
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
            }
            assert bases.intersection(allowed_bases) or "dataclass" in decorators, (
                f"{path.relative_to(ROOT)}:{node.name} is a concrete implementation in SPI"
            )


def test_private_authoring_modules_do_not_depend_on_framework_implementations() -> None:
    forbidden_prefixes = (
        "gaia.application",
        "gaia.api",
        "gaia.capabilities",
        "gaia.integrations",
        "gaia.persistence",
        "gaia.runtime",
        "gaia.starters",
    )
    for path in python_files(ROOT / "_authoring"):
        dependencies = imports(path)
        assert not any(name.startswith(forbidden_prefixes) for name in dependencies), (
            f"{path.relative_to(ROOT)} depends on a framework implementation"
        )


def test_legacy_sdk_package_is_removed() -> None:
    assert not (ROOT / "sdk").exists()
    assert importlib.util.find_spec("gaia.sdk") is None


def test_public_application_api_and_spi_have_distinct_surfaces() -> None:
    import gaia
    import gaia.spi

    assert {
        "ScenarioContext",
        "ScenarioResponse",
        "agent_handler",
        "continuation_handler",
        "fingerprint",
        "read_tool",
        "scenario",
        "write_tool",
    }.issubset(gaia.__all__)
    assert {"AuthnProvider", "ModelProvider", "Retriever", "WriteAdapter"}.issubset(
        gaia.spi.__all__
    )
    assert "ApiKeyAuthnProvider" not in gaia.spi.__all__
    assert "InProcessEventPublisher" not in gaia.spi.__all__


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


def test_framework_distribution_and_delivery_defaults_do_not_select_controlled_task() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    packages = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]

    assert packages == ["src/gaia"]

    delivery_paths = (
        PROJECT_ROOT / "Dockerfile",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "scripts" / "demo.py",
        PROJECT_ROOT / "scripts" / "export_openapi.py",
        PROJECT_ROOT / "scripts" / "smoke.py",
        PROJECT_ROOT / "infra" / "dev-full" / "compose.yaml",
        PROJECT_ROOT / "infra" / "dev-full" / "gaia.yaml",
        PROJECT_ROOT / "infra" / "production-like" / "compose.yaml",
        PROJECT_ROOT / "infra" / "production-like" / "compose.external.yaml",
        PROJECT_ROOT / "infra" / "production-like" / "gaia.yaml",
        PROJECT_ROOT / "infra" / "production-like" / "helm" / "gaia" / "values.yaml",
        PROJECT_ROOT
        / "infra"
        / "production-like"
        / "helm"
        / "gaia"
        / "values-external.example.yaml",
    )
    forbidden = ("controlled-task", "controlled_task")
    for path in delivery_paths:
        source = path.read_text()
        assert not any(value in source for value in forbidden), (
            f"{path.relative_to(PROJECT_ROOT)} selects the acceptance-only application"
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
    compose = yaml.safe_load((PROJECT_ROOT / "infra" / "dev" / "compose.yaml").read_text())

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
