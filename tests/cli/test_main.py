from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
import respx
from httpx import Response

from gaia.cli.main import main
from gaia.components import ComponentDescriptor, ComponentKind, ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.starters import OnProfile, StarterDescriptor
from gaia.testing import (
    ExpectedSubsetEvaluator,
    GaiaTestKit,
    RequiredMeasurementsGate,
    TestCase,
    TestObservation,
)


class CliCustomStarter:
    descriptor = StarterDescriptor("cli-custom", "1.0.0", ("custom",))

    def defaults(self) -> dict[str, object]:
        return {}

    def conditions(self) -> list[OnProfile]:
        return [OnProfile("mock")]

    def contribute(self, registry: ComponentRegistry, config: GaiaApplicationConfig) -> None:
        registry.register(
            ComponentDescriptor(
                component_id="custom-component",
                kind=ComponentKind.CONTEXT,
                implementation="tests.CliCustomStarter",
                starter_id=self.descriptor.starter_id,
                profile=config.profile,
                reason="cli-test",
            ),
            lambda _components: object(),
        )


def test_init_creates_complete_independent_project(tmp_path: Path) -> None:
    target = tmp_path / "demo-app"
    output: list[str] = []

    assert main(["init", str(target)], output=output.append) == 0

    expected_files = [
        "README.md",
        "pyproject.toml",
        "gaia.yaml",
        "src/demo_app/__init__.py",
        "src/demo_app/app.py",
        "src/demo_app/scenarios/hello.py",
        "prompts/hello/1.0.0.yaml",
        "tests/test_app.py",
        ".python-version",
        ".gitignore",
        ".env.example",
    ]
    for relative_path in expected_files:
        assert (target / relative_path).read_text().strip()
    project = (target / "pyproject.toml").read_text()
    assert 'requires-python = ">=3.12,<3.13"' in project
    assert '"pytest>=8.3,<9"' in project
    assert 'packages = ["src/demo_app"]' in project
    assert 'known-first-party = ["demo_app"]' in project
    assert "gaia-framework" in project
    assert (target / ".python-version").read_text() == "3.12\n"
    generated_app = (target / "src/demo_app/app.py").read_text()
    generated_test = (target / "tests/test_app.py").read_text()
    assert "def create_application():" in generated_app
    assert "resolve_config_path()" in generated_app
    assert "GAIA_CONFIG" not in generated_app
    assert "from demo_app.app import create_application" in generated_test
    assert "TestClient(create_application())" in generated_test
    assert "gaia dev" in (target / "README.md").read_text()
    assert "--app demo_app.app:app" in (target / "README.md").read_text()
    assert "--reload" in (target / "README.md").read_text()
    assert (target / "src/demo_app/scenarios/__init__.py").is_file()
    assert '@scenario(\n    "hello"' in (target / "src/demo_app/scenarios/hello.py").read_text()
    config = (target / "gaia.yaml").read_text()
    assert "environment: mock" in config
    assert "sandbox:" in config
    assert "environment: customer" in config
    assert "write_mode: disabled" in config
    assert "prompt-file" in config
    assert (
        'PromptRef(prompt_id="hello", version="1.0.0")'
        in (target / "src/demo_app/scenarios/hello.py").read_text()
    )
    assert (target / ".gaia/init.json").is_file()


def test_init_knowledge_template_activates_rag_dependencies(tmp_path: Path) -> None:
    target = tmp_path / "knowledge-app"

    assert main(["init", str(target), "--template", "knowledge"]) == 0

    config = (target / "gaia.yaml").read_text()
    scenario = (target / "src/knowledge_app/scenarios/knowledge.py").read_text()
    assert "rag-postgres" in config
    assert "embedding-openai-compatible" in config
    assert "knowledge.search" in scenario
    assert "RetrievalRequest" in scenario
    assert not (target / "src/knowledge_app/scenarios/hello.py").exists()


def test_init_approval_template_generates_human_gate_flow(tmp_path: Path) -> None:
    target = tmp_path / "approval-app"

    assert main(["init", str(target), "--template", "approval"]) == 0

    scenario = (target / "src/approval_app/scenarios/approval.py").read_text()
    application = (target / "src/approval_app/app.py").read_text()
    compile(scenario, "approval.py", "exec")
    compile(application, "app.py", "exec")
    assert "write_tools=(update_record,)" in application
    assert 'human_gate_rules=("all-writes",)' in scenario


def test_init_component_name_activates_its_starter(tmp_path: Path) -> None:
    target = tmp_path / "prompt-app"

    assert (
        main(
            [
                "init",
                str(target),
                "--component",
                "prompt-registry",
            ]
        )
        == 0
    )

    assert "prompt-postgres" in (target / "gaia.yaml").read_text()


def test_init_replaces_default_capability_starter(tmp_path: Path) -> None:
    target = tmp_path / "openai-app"

    assert main(["init", str(target), "--starter", "model-openai-compatible"]) == 0

    config = (target / "gaia.yaml").read_text()
    assert "model-openai-compatible" in config
    assert "model-mock" not in config
    assert "base_url: http://127.0.0.1:8001/v1" in config
    assert "GAIA_MODEL_API_KEY" in (target / ".env.example").read_text()
    assert main(["check", "--config", str(target / "gaia.yaml")]) == 0


def test_init_postgres_starter_adds_optional_dependency(tmp_path: Path) -> None:
    target = tmp_path / "postgres-app"

    assert main(["init", str(target), "--starter", "persistence-postgres"]) == 0

    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    assert "persistence-postgres" in (target / "gaia.yaml").read_text()
    assert "GAIA_POSTGRES_URL" in (target / "gaia.yaml").read_text()
    assert "operational:" in (target / "gaia.yaml").read_text()
    assert "provider: postgres" in (target / "gaia.yaml").read_text()
    assert "GAIA_POSTGRES_URL=" in (target / ".env.example").read_text()


def test_init_postgres_prompt_registry_replaces_file_provider(tmp_path: Path) -> None:
    target = tmp_path / "prompt-app"

    assert main(["init", str(target), "--starter", "prompt-postgres"]) == 0

    config = (target / "gaia.yaml").read_text()
    assert "prompt-postgres" in config
    assert "prompt-file" not in config
    assert "persistence-postgres" in config
    assert "provider: postgres" in config
    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    assert main(["check", "--config", str(target / "gaia.yaml")]) == 0


def test_init_rag_starter_adds_explicit_vector_embedding_and_rag_config(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rag-app"

    assert main(["init", str(target), "--starter", "rag-postgres"]) == 0

    config = (target / "gaia.yaml").read_text()
    assert "rag-postgres" in config
    assert "memory-postgres" in config
    assert "vector-pgvector" in config
    assert "embedding-openai-compatible" in config
    assert "namespace_prefix: gaia-rag" in config
    assert "GAIA_EMBEDDING_API_KEY" in config
    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    assert main(["check", "--config", str(target / "gaia.yaml")]) == 0


def test_init_redis_starters_add_optional_dependency_and_secret_reference(tmp_path: Path) -> None:
    target = tmp_path / "redis-app"

    assert (
        main(
            [
                "init",
                str(target),
                "--starter",
                "cache-redis",
                "--starter",
                "rate-limit-redis",
            ]
        )
        == 0
    )

    assert "gaia-framework[redis]" in (target / "pyproject.toml").read_text()
    config = (target / "gaia.yaml").read_text()
    assert "redis-client" in config
    assert "cache-redis" in config
    assert "rate-limit-redis" in config
    assert "GAIA_REDIS_URL" in config
    assert "GAIA_REDIS_URL=" in (target / ".env.example").read_text()


def test_init_outbox_adds_postgres_and_in_process_publisher_dependencies(tmp_path: Path) -> None:
    target = tmp_path / "outbox-app"

    assert main(["init", str(target), "--starter", "outbox-postgres"]) == 0

    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    config = (target / "gaia.yaml").read_text()
    assert "persistence-postgres" in config
    assert "publisher-in-process" in config
    assert "outbox-postgres" in config
    assert main(["check", "--config", str(target / "gaia.yaml")]) == 0


def test_init_combines_postgres_and_redis_extras(tmp_path: Path) -> None:
    target = tmp_path / "infrastructure-app"

    assert (
        main(
            [
                "init",
                str(target),
                "--starter",
                "outbox-postgres",
                "--starter",
                "cache-redis",
            ]
        )
        == 0
    )

    assert "gaia-framework[postgres,redis]" in (target / "pyproject.toml").read_text()


def test_check_expands_declared_starter_dependencies(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  starters: [outbox-postgres]\n")
    output: list[str] = []

    assert main(["check", "--config", str(config)], output=output.append) == 0

    components = set(json.loads(output[0])["components"])
    assert components == {"persistence-postgres", "publisher-in-process", "outbox-postgres"}


def test_init_rejects_non_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    output: list[str] = []

    assert main(["init", str(target)], output=output.append) == 2
    assert "non-empty" in output[0]


def test_add_workflow_creates_application_owned_graph_and_tests(tmp_path: Path) -> None:
    target = tmp_path / "workflow-app"

    assert main(["init", str(target)]) == 0
    assert (
        main(
            [
                "add-workflow",
                "contract-review",
                "--directory",
                str(target),
            ]
        )
        == 0
    )

    workflow = target / "src/workflow_app/workflows/contract_review.py"
    test = target / "tests/workflows/test_contract_review.py"
    assert workflow.exists()
    assert test.exists()
    assert "StateGraph" in workflow.read_text()
    assert '["validate", "process"]' in test.read_text()
    compile(workflow.read_text(), str(workflow), "exec")
    compile(test.read_text(), str(test), "exec")
    assert main(["add-workflow", "contract-review", "--directory", str(target)]) == 2


def test_check_reports_components_and_conditions(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  profile: mock\n")
    output: list[str] = []

    assert main(["check", "--config", str(config)], output=output.append) == 0

    report = json.loads(output[0])
    assert report["ok"] is True
    assert report["components"]
    assert report["conditions"]


def test_check_returns_two_for_invalid_configuration(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("not-gaia: true\n")
    output: list[str] = []

    assert main(["check", "--config", str(config)], output=output.append) == 2
    report = json.loads(output[0])
    assert report["ok"] is False
    assert report["message"] == "Configuration validation failed."
    assert "gaia.yaml" in report["operator_action"]


def test_doctor_probes_sqlite_and_skips_disabled_dependencies(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    database = tmp_path / "not-created-yet" / "doctor.db"
    config.write_text(f"gaia:\n  runtime:\n    database_url: sqlite+aiosqlite:///{database}\n")
    output: list[str] = []

    assert main(["doctor", "--config", str(config)], output=output.append) == 0

    report = json.loads(output[0])
    assert report["ok"] is True
    statuses = {item["check_id"]: item["status"] for item in report["checks"]}
    assert statuses == {
        "configuration": "passed",
        "database.operational": "passed",
        "redis": "skipped",
        "model": "skipped",
        "embedding": "skipped",
    }


def test_doctor_accepts_explicit_profile_option(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  profile: mock\n"
        "  profiles:\n"
        "    sandbox:\n"
        "      runtime:\n"
        "        environment: sandbox\n"
    )
    output: list[str] = []

    assert (
        main(
            ["doctor", "--config", str(config), "--profile", "sandbox"],
            output=output.append,
        )
        == 0
    )

    assert json.loads(output[0])["profile"] == "sandbox"


def test_doctor_reports_missing_secret_as_actionable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISSING_DATABASE_URL", raising=False)
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  runtime:\n    database_url:\n      env: MISSING_DATABASE_URL\n")
    output: list[str] = []

    assert main(["doctor", "--config", str(config)], output=output.append) == 2

    report = json.loads(output[0])
    failed = next(item for item in report["checks"] if item["status"] == "failed")
    assert failed["check_id"] == "database.operational"
    assert failed["message"] == "A required secret reference is unavailable."
    assert "database secret" in failed["operator_action"]


def test_doctor_probes_openai_compatible_models_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_MODEL_API_KEY", "secret-value")
    config = tmp_path / "gaia.yaml"
    database = tmp_path / "doctor-model.db"
    config.write_text(
        "\n".join(
            (
                "gaia:",
                "  runtime:",
                f"    database_url: sqlite+aiosqlite:///{database}",
                "  model:",
                "    provider: openai-compatible",
                "    base_url: https://model.example/v1",
                "    api_key:",
                "      env: TEST_MODEL_API_KEY",
                "",
            )
        )
    )
    output: list[str] = []

    with respx.mock() as router:
        route = router.get(
            "https://model.example/v1/models",
            headers={"Authorization": "Bearer secret-value"},
        ).mock(return_value=Response(200, json={"data": []}))
        assert main(["doctor", "--config", str(config)], output=output.append) == 0

    assert route.called
    report = json.loads(output[0])
    model = next(item for item in report["checks"] if item["check_id"] == "model")
    assert model["status"] == "passed"


def test_check_validates_imported_starter(tmp_path: Path) -> None:
    module = ModuleType("temporary_cli_starter")
    module.starter = CliCustomStarter()
    sys.modules[module.__name__] = module
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  starters:\n    - import: temporary_cli_starter:starter\n")
    output: list[str] = []
    try:
        assert main(["check", "--config", str(config)], output=output.append) == 0
    finally:
        del sys.modules[module.__name__]
    assert "custom-component" in output[0]


def test_starters_lists_builtin_starters() -> None:
    output: list[str] = []

    assert main(["starters"], output=output.append) == 0

    starters = json.loads(output[0])
    assert any(item["starter_id"] == "core-runtime" for item in starters)


def test_prompt_command_requires_postgres_provider(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  prompt:\n    provider: file\n")
    artifact = tmp_path / "prompt.yaml"
    artifact.write_text(
        "prompt_id: hello\nversion: 1.0.0\nmessages:\n  - role: system\n    content: Hello.\n"
    )
    output: list[str] = []

    status = main(
        [
            "prompt",
            "import",
            str(artifact),
            "--config",
            str(config),
            "--actor",
            "developer",
        ],
        output=output.append,
    )

    assert status == 2
    assert "prompt.provider=postgres" in output[0]


def test_dev_loads_configuration_and_calls_injected_server_runner(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  runtime:\n    database_url: sqlite+aiosqlite:///./demo.db\n")
    calls: list[tuple[object, str, int, bool]] = []

    def runner(application: object, *, host: str, port: int, reload: bool) -> None:
        calls.append((application, host, port, reload))

    def api_factory(*, database_url: str, gaia_application: object) -> object:
        assert database_url == "sqlite+aiosqlite:///./demo.db"
        assert gaia_application is not None
        return object()

    assert (
        main(
            ["dev", "--config", str(config), "--host", "0.0.0.0", "--port", "9010"],
            server_runner=runner,
            api_factory=api_factory,
        )
        == 0
    )
    assert calls[0][1:] == ("0.0.0.0", 9010, False)


def test_check_uses_canonical_config_path_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "custom-gaia.yaml"
    config.write_text("gaia:\n  application: {name: environment-selected}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GAIA_CONFIG_PATH", str(config))
    output: list[str] = []

    assert main(["check"], output=output.append) == 0

    payload = json.loads(output[0])
    assert payload["ok"] is True
    assert payload["components"]


def test_dev_can_reload_an_explicit_application_import_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  profile: mock\n")
    monkeypatch.delenv("GAIA_CONFIG_PATH", raising=False)
    calls: list[tuple[object, str, int, bool, str | None]] = []

    def runner(application: object, *, host: str, port: int, reload: bool) -> None:
        calls.append(
            (
                application,
                host,
                port,
                reload,
                os.environ.get("GAIA_CONFIG_PATH"),
            )
        )

    assert (
        main(
            [
                "dev",
                "--config",
                str(config),
                "--app",
                "demo_app.app:app",
                "--reload",
            ],
            server_runner=runner,
        )
        == 0
    )
    assert calls == [("demo_app.app:app", "127.0.0.1", 8000, True, str(config.resolve()))]
    assert "GAIA_CONFIG_PATH" not in os.environ


def test_dev_rejects_reload_without_an_application_import_string(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  profile: mock\n")

    assert main(["dev", "--config", str(config), "--reload"]) == 2


def test_test_command_runs_dataset_and_writes_report(tmp_path: Path) -> None:
    class Executor:
        async def execute(self, case: TestCase, *, attempt: int) -> TestObservation:
            return TestObservation(
                case_id=case.case_id,
                attempt=attempt,
                actual={"answer": case.input["answer"]},
            )

    module = ModuleType("temporary_test_kit")
    module.create_kit = lambda: GaiaTestKit(
        Executor(),
        evaluators=(ExpectedSubsetEvaluator(),),
        gates=(RequiredMeasurementsGate(),),
    )
    sys.modules[module.__name__] = module
    dataset = tmp_path / "golden.yaml"
    dataset.write_text(
        "dataset_id: smoke\n"
        'version: "1"\n'
        "cases:\n"
        "  - case_id: example\n"
        "    input: {answer: ok}\n"
        "    expected: {answer: ok}\n"
    )
    report_path = tmp_path / "reports" / "latest.json"
    output: list[str] = []
    try:
        status = main(
            [
                "test",
                str(dataset),
                "--kit",
                "temporary_test_kit:create_kit",
                "--subject",
                "revision=abc123",
                "--output",
                str(report_path),
            ],
            output=output.append,
        )
    finally:
        del sys.modules[module.__name__]

    assert status == 0
    report = json.loads(output[0])
    assert report["passed"] is True
    assert report["subject"] == {"revision": "abc123"}
    assert json.loads(report_path.read_text())["dataset_id"] == "smoke"


def test_migrate_creates_sqlite_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  runtime:\n    database_url: sqlite+aiosqlite:///./var/gaia.db\n")
    monkeypatch.chdir(tmp_path)

    assert main(["migrate", "--config", str(config)]) == 0

    assert (tmp_path / "var" / "gaia.db").is_file()
