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
from gaia.diagnostics.error_catalog import error_descriptor
from gaia.starters import OnProfile, StarterDescriptor
from gaia.testing import (
    ExpectedSubsetEvaluator,
    GaiaTestKit,
    RequiredMeasurementsGate,
    TestCase,
    TestObservation,
    load_dataset,
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
    # The scaffolded test must pass on a bare `pytest`, immediately after
    # `gaia init`. Driving the HTTP API would now require a running Temporal
    # server and Worker, so a brand-new project's first command would fail on
    # infrastructure rather than on anything the author wrote.
    assert "from demo_app.scenarios.hello import hello" in generated_test
    assert "ScenarioTestHarness(hello)" in generated_test
    assert "TestClient" not in generated_test
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
    assert "provider: in_process" in config
    assert "provider: temporal" in config
    assert "topology:" not in config
    assert "prompt-file" in config
    assert (
        'PromptRef(prompt_id="hello", version="1.0.0")'
        in (target / "src/demo_app/scenarios/hello.py").read_text()
    )
    assert (target / ".gaia/init.json").is_file()
    dataset = (target / "tests/scenario-cases.yaml").read_text()
    assert "case_id: normal" in dataset
    assert "case_id: policy-boundary" in dataset
    assert "case_id: dependency-failure" in dataset


def test_init_knowledge_template_activates_rag_dependencies(tmp_path: Path) -> None:
    target = tmp_path / "knowledge-app"

    assert main(["init", str(target), "--template", "knowledge"]) == 0

    config = (target / "gaia.yaml").read_text()
    scenario = (target / "src/knowledge_app/scenarios/knowledge.py").read_text()
    assert "rag-postgres" in config
    assert "embedding-openai-compatible" in config
    assert "knowledge.search" in scenario
    assert "RetrievalRequest" in scenario
    assert "provider: in_process" in config
    dataset = load_dataset(target / "tests/scenario-cases.yaml")
    dependency_case = next(case for case in dataset.cases if case.case_id == "dependency-failure")
    assert dependency_case.input["dependency"] == "retriever"
    assert not (target / "src/knowledge_app/scenarios/hello.py").exists()


def test_init_approval_template_generates_human_gate_flow(tmp_path: Path) -> None:
    target = tmp_path / "approval-app"

    assert main(["init", str(target), "--template", "approval"]) == 0

    scenario = (target / "src/approval_app/scenarios/approval.py").read_text()
    application = (target / "src/approval_app/app.py").read_text()
    config = (target / "gaia.yaml").read_text()
    compile(scenario, "approval.py", "exec")
    compile(application, "app.py", "exec")
    # A7: the write scenario and its write tool are discovered declaratively from
    # `scenarios.modules`, not hand-wired with `GaiaAppBuilder(...).scenarios(...).tools(...)`.
    assert "GaiaAppBuilder" not in application
    assert "dependencies=" not in application
    assert "resolve_config_path()" in application
    assert "scenario-runtime" in config
    assert "approval_app.scenarios.approval" in config
    assert "provider: temporal" in config
    assert "provider: in_process" not in config
    assert "topology:" not in config
    assert 'human_gate_rules=("all-writes",)' in scenario
    assert "approval_view=ApprovalView(" in scenario
    assert "pending_result=" in scenario
    dataset = load_dataset(target / "tests/scenario-cases.yaml")
    dependency_case = next(case for case in dataset.cases if case.case_id == "dependency-failure")
    assert dependency_case.input["dependency"] == "write-adapter"


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


def test_init_replaces_default_capability_starter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "openai-app"

    assert main(["init", str(target), "--starter", "model-openai-compatible"]) == 0

    config = (target / "gaia.yaml").read_text()
    assert "model-openai-compatible" in config
    assert "model-mock" not in config
    assert "base_url: http://127.0.0.1:8001/v1" in config
    assert "GAIA_MODEL_API_KEY" in (target / ".env.example").read_text()
    # `gaia check` now resolves `scenarios.modules`, so the generated package must be
    # importable, exactly as it would be after `uv add --editable` + `uv sync` in a real
    # generated project (see developer-docs/getting-started.md).
    monkeypatch.syspath_prepend(str(target / "src"))
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


def test_init_postgres_prompt_registry_replaces_file_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "prompt-app"

    assert main(["init", str(target), "--starter", "prompt-postgres"]) == 0

    config = (target / "gaia.yaml").read_text()
    assert "prompt-postgres" in config
    assert "prompt-file" not in config
    assert "persistence-postgres" in config
    assert "provider: postgres" in config
    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    monkeypatch.syspath_prepend(str(target / "src"))
    assert main(["check", "--config", str(target / "gaia.yaml")]) == 0


def test_init_rag_starter_adds_explicit_vector_embedding_and_rag_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.syspath_prepend(str(target / "src"))
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


def test_init_outbox_adds_postgres_and_in_process_publisher_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "outbox-app"

    assert main(["init", str(target), "--starter", "outbox-postgres"]) == 0

    assert "gaia-framework[postgres]" in (target / "pyproject.toml").read_text()
    config = (target / "gaia.yaml").read_text()
    assert "persistence-postgres" in config
    assert "publisher-in-process" in config
    assert "outbox-postgres" in config
    monkeypatch.syspath_prepend(str(target / "src"))
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


def test_check_reports_catalog_operator_action_for_unimportable_scenario_module(
    tmp_path: Path,
) -> None:
    """A brand-new user's first `gaia check` after `gaia init` fails because the generated
    package is not yet installed. The error code (`SCENARIO_MODULE_NOT_FOUND`) is precise
    either way, but the operator action must point at installing the project, not at
    editing gaia.yaml -- the same class of misdiagnosis task A2 fixed for transitive
    imports. This pins that `_check` prefers the error catalog's specific guidance over
    the generic gaia.yaml/profile/Starter action whenever the failure is a
    `ScenarioDiscoveryError`.
    """

    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  starters: [core-runtime, model-mock, scenario-runtime]\n"
        "  scenarios:\n"
        "    modules: [nonexistent_app.scenarios.hello]\n"
    )
    output: list[str] = []

    assert main(["check", "--config", str(config)], output=output.append) == 2

    report = json.loads(output[0])
    assert report["ok"] is False
    assert report["issues"] == ["SCENARIO_MODULE_NOT_FOUND:nonexistent_app.scenarios.hello"]
    expected_action = error_descriptor("SCENARIO_MODULE_NOT_FOUND").operator_action
    assert report["operator_action"] == expected_action
    assert "install" in report["operator_action"].lower()
    generic_action = "Correct the reported gaia.yaml, profile, secret reference, or Starter issue."
    assert report["operator_action"] != generic_action


def test_check_reports_import_purity_findings_and_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2.1's AST purity scan must run before `configure()` and surface as a `gaia check`
    failure: a scenario module that resolves a secret at import time is a real, importable
    module (unlike the `SCENARIO_MODULE_NOT_FOUND` case above), so without the purity scan
    this would sail through `configure()` and actually resolve the secret."""

    module_name = "cli_test_impure_scenario_module"
    (tmp_path / f"{module_name}.py").write_text(
        "from gaia.config.secrets import resolve_secret\n"
        "\n"
        'SECRET = resolve_secret("db-password")\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  starters: [core-runtime, model-mock, scenario-runtime]\n"
        "  scenarios:\n"
        f"    modules: [{module_name}]\n"
    )
    output: list[str] = []

    assert main(["check", "--config", str(config)], output=output.append) == 2

    report = json.loads(output[0])
    assert report["ok"] is False
    assert len(report["issues"]) == 1
    assert module_name in report["issues"][0]
    assert "gaia.config.secrets.resolve_secret" in report["issues"][0]


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


def test_worker_loads_application_composition_and_restores_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text(
        "gaia:\n"
        "  profile: mock\n"
        "  runtime:\n"
        "    execution:\n"
        "      provider: temporal\n"
        "      namespace: demo\n"
        "      task_queue: demo-worker\n"
    )
    monkeypatch.setenv("GAIA_CONFIG_PATH", "original.yaml")
    monkeypatch.setenv("GAIA__PROFILE", "original")
    calls: list[tuple[str, str | None, str | None]] = []
    output: list[str] = []

    def worker_runner(application: object, app_target: str) -> None:
        assert application is not None
        calls.append(
            (
                app_target,
                os.environ.get("GAIA_CONFIG_PATH"),
                os.environ.get("GAIA__PROFILE"),
            )
        )

    assert (
        main(
            [
                "worker",
                "--config",
                str(config),
                "--app",
                "examples.controlled_task.app:create_app",
            ],
            worker_runner=worker_runner,
            output=output.append,
        )
        == 0
    )
    assert calls == [
        (
            "examples.controlled_task.app:create_app",
            str(config.resolve()),
            "original",
        )
    ]
    assert os.environ["GAIA_CONFIG_PATH"] == "original.yaml"
    assert os.environ["GAIA__PROFILE"] == "original"
    assert output == ["starting Temporal Worker namespace=demo task_queue=demo-worker"]


def test_worker_reports_runner_failure(tmp_path: Path) -> None:
    config = tmp_path / "gaia.yaml"
    config.write_text("gaia:\n  profile: mock\n")
    output: list[str] = []

    def worker_runner(application: object, app_target: str) -> None:
        del application, app_target
        raise RuntimeError("Temporal is unavailable")

    assert (
        main(
            [
                "worker",
                "--config",
                str(config),
                "--app",
                "examples.controlled_task.app:create_app",
            ],
            worker_runner=worker_runner,
            output=output.append,
        )
        == 2
    )
    assert output[-1] == "gaia worker failed: Temporal is unavailable"


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
