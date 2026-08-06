"""Thin, testable command-line interface for Gaia application projects."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tomllib
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from gaia.application import GaiaApplication
from gaia.cli.prompts import execute_prompt_command, prompt_result_json
from gaia.config import resolve_config_path, resolve_secret
from gaia.contracts.models import RunMode
from gaia.diagnostics.doctor import run_doctor
from gaia.diagnostics.error_catalog import error_descriptor
from gaia.diagnostics.import_purity import PurityFinding, scan_module_purity
from gaia.starters import BUILTIN_STARTERS, ScenarioDiscoveryError
from gaia.templates import (
    COMPONENT_STARTERS,
    SCENARIO_TEMPLATES,
    project_files,
    selected_starters,
    workflow_files,
)
from gaia.testing import GaiaTestKit, load_dataset

Output = Callable[[str], None]
ServerRunner = Callable[..., None]
ApiFactory = Callable[..., Any]
WorkerRunner = Callable[[GaiaApplication, str], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gaia")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize an independent Gaia application project")
    init.add_argument("directory", type=Path)
    init.add_argument("--name", help="application package name; defaults to the directory name")
    init.add_argument(
        "--template",
        choices=tuple(SCENARIO_TEMPLATES),
        default="basic",
        help="select an application scenario template",
    )
    init.add_argument(
        "--component",
        action="append",
        choices=tuple(COMPONENT_STARTERS),
        default=[],
        help="activate an optional component using a developer-friendly name",
    )
    init.add_argument(
        "--starter",
        dest="starters",
        action="append",
        choices=tuple(BUILTIN_STARTERS),
        default=[],
        help="select or replace a built-in capability starter",
    )

    workflow = commands.add_parser(
        "add-workflow",
        help="add an application-owned workflow and routing tests",
    )
    workflow.add_argument("name")
    workflow.add_argument("--directory", type=Path, default=Path("."))

    check = commands.add_parser("check", help="validate configuration and auto-configuration")
    _config_argument(check)
    check.add_argument("--set", dest="overrides", action="append", default=[])

    doctor = commands.add_parser("doctor", help="probe configured external dependencies")
    _config_argument(doctor)
    doctor.add_argument("--set", dest="overrides", action="append", default=[])

    commands.add_parser("starters", help="list built-in starters")

    migrate = commands.add_parser("migrate", help="upgrade Gaia operational tables")
    _config_argument(migrate)
    migrate.add_argument("--set", dest="overrides", action="append", default=[])
    migrate.add_argument("--revision", default="head")

    dev = commands.add_parser("dev", help="load an application and start its ASGI server")
    _config_argument(dev)
    dev.add_argument("--set", dest="overrides", action="append", default=[])
    dev.add_argument("--host", default="127.0.0.1")
    dev.add_argument("--port", type=int, default=8000)
    dev.add_argument(
        "--app",
        dest="app_target",
        help="ASGI import string, for example my_app.app:app",
    )
    dev.add_argument(
        "--reload",
        action="store_true",
        help="reload the ASGI application after source changes; requires --app",
    )

    worker = commands.add_parser(
        "worker",
        help="run the Temporal Worker for an application composition",
    )
    _config_argument(worker)
    worker.add_argument("--set", dest="overrides", action="append", default=[])
    worker.add_argument(
        "--app",
        dest="app_target",
        required=True,
        help="ASGI application factory import string, for example my_app.app:create_app",
    )

    test = commands.add_parser("test", help="run a Gaia Test Kit dataset")
    test.add_argument("dataset", type=Path)
    test.add_argument(
        "--kit",
        required=True,
        help="factory import string returning GaiaTestKit, for example tests.eval:create_kit",
    )
    test.add_argument("--repetitions", type=int, default=1)
    test.add_argument("--subject", action="append", default=[], metavar="KEY=VALUE")
    test.add_argument("--output", type=Path, default=None)

    prompt = commands.add_parser("prompt", help="manage immutable Prompt Registry versions")
    prompt_commands = prompt.add_subparsers(dest="prompt_command", required=True)

    prompt_import = prompt_commands.add_parser("import", help="import a YAML artifact as draft")
    prompt_import.add_argument("artifact", type=Path)
    _prompt_common(prompt_import)

    prompt_diff = prompt_commands.add_parser("diff", help="diff YAML against the same version")
    prompt_diff.add_argument("artifact", type=Path)
    _prompt_common(prompt_diff)

    prompt_validate = prompt_commands.add_parser(
        "validate",
        help="attach a passing Gaia Test Kit report",
    )
    prompt_validate.add_argument("prompt_id")
    prompt_validate.add_argument("version")
    prompt_validate.add_argument("--report", type=Path, required=True)
    _prompt_common(prompt_validate)

    for command, help_text in (
        ("publish", "move an environment release pointer"),
        ("rollback", "move an environment pointer to a prior published version"),
    ):
        command_parser = prompt_commands.add_parser(command, help=help_text)
        command_parser.add_argument("prompt_id")
        command_parser.add_argument("version")
        command_parser.add_argument(
            "--environment",
            choices=tuple(item.value for item in RunMode),
            required=True,
        )
        _prompt_common(command_parser)
    return parser


def _prompt_common(parser: argparse.ArgumentParser) -> None:
    _config_argument(parser)
    parser.add_argument("--actor", required=True)


def _config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="configuration file; overrides GAIA_CONFIG_PATH and defaults to gaia.yaml",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="activate a gaia.yaml profile for this command",
    )


def _config_overrides(args: argparse.Namespace) -> list[str]:
    overrides = list(getattr(args, "overrides", []))
    profile = getattr(args, "profile", None)
    if profile is not None:
        overrides.append(f"profile={profile}")
    return overrides


def _selected_starters(requested: list[str]) -> tuple[str, ...]:
    return selected_starters("basic", explicit_starters=tuple(requested))


def _write_project(
    directory: Path,
    name: str,
    starters: tuple[str, ...],
    *,
    template_id: str = "basic",
) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    for relative_path, contents in project_files(
        name,
        starters,
        template_id=template_id,
    ).items():
        target = directory / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")


def _write_workflow(directory: Path, name: str) -> tuple[Path, ...]:
    project = directory / "pyproject.toml"
    if not project.exists():
        raise ValueError("pyproject.toml was not found in the application directory")
    data = tomllib.loads(project.read_text(encoding="utf-8"))
    try:
        packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        package_path = Path(str(packages[0]))
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Gaia application package path was not found in pyproject.toml") from error
    if package_path.parent != Path("src"):
        raise ValueError("Gaia workflow templates require a src package layout")
    application_module = package_path.name
    files = workflow_files(application_module, name)
    targets = tuple(directory / relative_path for relative_path in files)
    conflicts = [target for target in targets if target.exists()]
    if conflicts:
        raise ValueError(f"refusing to overwrite workflow file: {conflicts[0]}")
    package_init = directory / "src" / application_module / "workflows" / "__init__.py"
    tests_init = directory / "tests" / "workflows" / "__init__.py"
    for init in (package_init, tests_init):
        if not init.exists():
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_text("", encoding="utf-8")
    for target, contents in zip(targets, files.values(), strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return targets


def _condition_data(report: Any) -> dict[str, object]:
    return {
        "starter_id": report.starter_id,
        "matched": report.matched,
        "reasons": list(report.reasons),
    }


def _check_failure_operator_action(error: Exception) -> str:
    """Prefer the error catalog's specific guidance when the failure carries a known code.

    `ScenarioDiscoveryError` (raised by `discover_scenarios` when `scenarios.modules`
    fails to import, or declares a duplicate scenario/tool/agent/continuation name) is
    the common case: its `.code` is a stable machine code the error catalog already has
    real operator guidance for (e.g. `SCENARIO_MODULE_NOT_FOUND` -> "install the project
    so its package is importable"). Falling back to the generic gaia.yaml-focused action
    for that case sends a brand-new user -- this is typically the very first command they
    run after `gaia init` -- to edit the wrong file. Every other configuration failure
    (bad YAML, unresolved Starter, invalid profile, ...) keeps the generic action.
    """

    if isinstance(error, ScenarioDiscoveryError):
        return error_descriptor(error.code).operator_action
    return "Correct the reported gaia.yaml, profile, secret reference, or Starter issue."


def _purity_issue(finding: PurityFinding) -> str:
    return f"{finding.module}:{finding.line}: {finding.symbol} - {finding.hint}"


def _check(config_path: Path, overrides: list[str], output: Output) -> int:
    try:
        application = GaiaApplication.from_config(config_path, overrides=overrides)
        # A2.1: scan every declared scenario module for import-time I/O *before*
        # configure() runs. After A4, configure() imports these modules for real via the
        # scenario-runtime Starter, so scanning afterward would be pointless -- any real
        # side effect the scan is meant to catch would already have happened.
        purity_findings = tuple(
            finding
            for module_name in application.config.scenarios.modules
            for finding in scan_module_purity(module_name)
        )
        if purity_findings:
            output(
                json.dumps(
                    {
                        "ok": False,
                        "message": "Scenario module import-purity check failed.",
                        "operator_action": (
                            "Move the flagged calls into a Starter component registered "
                            "with ComponentScope.APPLICATION so the application lifespan "
                            "manages them; scenario modules must stay import-pure. This "
                            "is a best-effort lint, not an isolation guarantee -- see "
                            "gaia.diagnostics.import_purity for what it does and does not "
                            "catch."
                        ),
                        "issues": [_purity_issue(finding) for finding in purity_findings],
                        "components": [],
                        "conditions": [],
                    }
                )
            )
            return 2
        context = asyncio.run(application.configure())
    except Exception as error:  # CLI must turn config/application errors into a stable exit code.
        output(
            json.dumps(
                {
                    "ok": False,
                    "message": "Configuration validation failed.",
                    "operator_action": _check_failure_operator_action(error),
                    "issues": [str(error)],
                    "components": [],
                    "conditions": [],
                }
            )
        )
        return 2
    report = context.auto_configuration_report
    conditions = (
        []
        if report is None
        else [
            *(_condition_data(item) for item in report.positive),
            *(_condition_data(item) for item in report.negative),
        ]
    )
    payload = {
        "ok": True,
        "issues": [],
        "components": [item.component_id for item in context.descriptors],
        "conditions": conditions,
    }
    output(json.dumps(payload, sort_keys=True))
    return 0


def _starters(output: Output) -> int:
    payload = [
        {
            "starter_id": starter.descriptor.starter_id,
            "version": starter.descriptor.version,
            "capabilities": list(starter.descriptor.capabilities),
            "defaults": starter.defaults(),
            "conditions": [condition.__class__.__name__ for condition in starter.conditions()],
        }
        for starter in BUILTIN_STARTERS.values()
    ]
    output(json.dumps(payload, sort_keys=True))
    return 0


def _prompt(args: argparse.Namespace, output: Output) -> int:
    try:
        config = GaiaApplication.from_config(
            args.config,
            overrides=_config_overrides(args),
        ).config
        environment_value = getattr(args, "environment", None)
        result = asyncio.run(
            execute_prompt_command(
                config,
                command=cast(str, args.prompt_command),
                actor=cast(str, args.actor),
                artifact_path=getattr(args, "artifact", None),
                report_path=getattr(args, "report", None),
                prompt_id=getattr(args, "prompt_id", None),
                version=getattr(args, "version", None),
                environment=(None if environment_value is None else RunMode(environment_value)),
            )
        )
    except Exception as error:
        output(prompt_result_json({"ok": False, "error": str(error)}))
        return 2
    output(prompt_result_json({"ok": True, "result": result}))
    return 0


def _doctor(config_path: Path, overrides: list[str], output: Output) -> int:
    try:
        application = GaiaApplication.from_config(config_path, overrides=overrides)
        report = asyncio.run(run_doctor(application))
    except Exception as error:
        output(
            json.dumps(
                {
                    "ok": False,
                    "application_name": None,
                    "profile": None,
                    "checks": [],
                    "message": "Dependency diagnostics could not start.",
                    "operator_action": (
                        "Run gaia check first, then correct the reported configuration issue."
                    ),
                    "issues": [str(error)],
                },
                sort_keys=True,
            )
        )
        return 2
    output(report.model_dump_json())
    return 0 if report.ok else 2


def _migrate(config_path: Path, overrides: list[str], revision: str, output: Output) -> int:
    try:
        from gaia.persistence.migrate import upgrade_database

        application = GaiaApplication.from_config(config_path, overrides=overrides)
        database_url = resolve_secret(application.config.runtime.database_url)
        upgrade_database(database_url, revision)
    except Exception as error:
        output(f"gaia migrate failed: {error}")
        return 2
    output(f"migrated Gaia operational schema to {revision}")
    return 0


def _default_server_runner(
    application: Any,
    *,
    host: str,
    port: int,
    reload: bool,
) -> None:
    import uvicorn

    uvicorn.run(application, host=host, port=port, reload=reload)


def _default_api_factory(*, database_url: str, gaia_application: GaiaApplication) -> Any:
    from gaia.api.app import create_app

    return create_app(database_url=database_url, gaia_application=gaia_application)


def _import_target(target: str) -> Any:
    module_name, separator, attribute_name = target.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("import target must use module:attribute")
    return getattr(import_module(module_name), attribute_name)


async def _serve_temporal_worker(
    application: GaiaApplication,
    app_target: str,
) -> None:
    from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
    from gaia.runtime.temporal_worker import run_temporal_worker

    imported = _import_target(app_target)
    app = imported() if callable(imported) else imported
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        if not isinstance(runtime, TemporalRuntimeEngine):
            raise ValueError("application does not expose a TemporalRuntimeEngine")
        await run_temporal_worker(
            execution=application.config.runtime.execution,
            runtime=runtime,
        )


def _default_worker_runner(
    application: GaiaApplication,
    app_target: str,
) -> None:
    asyncio.run(_serve_temporal_worker(application, app_target))


def _worker(
    config_path: Path,
    overrides: list[str],
    app_target: str,
    worker_runner: WorkerRunner,
    output: Output,
) -> int:
    try:
        application = GaiaApplication.from_config(config_path, overrides=overrides)
        previous_config_path = os.environ.get("GAIA_CONFIG_PATH")
        previous_profile = os.environ.get("GAIA__PROFILE")
        try:
            os.environ["GAIA_CONFIG_PATH"] = str(config_path)
            os.environ["GAIA__PROFILE"] = application.config.profile
            output(
                "starting Temporal Worker "
                f"namespace={application.config.runtime.execution.namespace} "
                f"task_queue={application.config.runtime.execution.task_queue}"
            )
            worker_runner(application, app_target)
        finally:
            if previous_config_path is None:
                os.environ.pop("GAIA_CONFIG_PATH", None)
            else:
                os.environ["GAIA_CONFIG_PATH"] = previous_config_path
            if previous_profile is None:
                os.environ.pop("GAIA__PROFILE", None)
            else:
                os.environ["GAIA__PROFILE"] = previous_profile
    except Exception as error:
        output(f"gaia worker failed: {error}")
        return 2
    return 0


def _dev(
    config_path: Path,
    overrides: list[str],
    host: str,
    port: int,
    app_target: str | None,
    reload: bool,
    server_runner: ServerRunner,
    api_factory: ApiFactory,
) -> int:
    try:
        if reload and app_target is None:
            raise ValueError("--reload requires --app with an ASGI import string")
        application = GaiaApplication.from_config(config_path, overrides=overrides)
        asyncio.run(application.configure())
        server = (
            app_target
            if app_target is not None
            else api_factory(
                database_url=resolve_secret(application.config.runtime.database_url),
                gaia_application=application,
            )
        )
        previous_config_path = os.environ.get("GAIA_CONFIG_PATH")
        previous_profile = os.environ.get("GAIA__PROFILE")
        try:
            if app_target is not None:
                os.environ["GAIA_CONFIG_PATH"] = str(config_path)
                os.environ["GAIA__PROFILE"] = application.config.profile
            server_runner(server, host=host, port=port, reload=reload)
        finally:
            if app_target is not None:
                if previous_config_path is None:
                    os.environ.pop("GAIA_CONFIG_PATH", None)
                else:
                    os.environ["GAIA_CONFIG_PATH"] = previous_config_path
                if previous_profile is None:
                    os.environ.pop("GAIA__PROFILE", None)
                else:
                    os.environ["GAIA__PROFILE"] = previous_profile
    except Exception as error:  # CLI startup failures should not leak an argparse traceback.
        print(f"gaia dev failed: {error}", file=sys.stderr)
        return 2
    return 0


def _test(
    dataset_path: Path,
    kit_target: str,
    repetitions: int,
    subject_items: list[str],
    report_path: Path | None,
    output: Output,
) -> int:
    try:
        module_name, separator, factory_name = kit_target.partition(":")
        if not separator or not module_name or not factory_name:
            raise ValueError("--kit must use module:function syntax")
        factory = getattr(import_module(module_name), factory_name)
        kit = factory()
        if not isinstance(kit, GaiaTestKit):
            raise TypeError("test kit factory must return GaiaTestKit")
        subject: dict[str, str] = {}
        for item in subject_items:
            key, separator, value = item.partition("=")
            if not separator or not key:
                raise ValueError("--subject must use KEY=VALUE syntax")
            subject[key] = value
        report = asyncio.run(
            kit.run(
                load_dataset(dataset_path),
                subject=subject,
                repetitions=repetitions,
            )
        )
        serialized = report.model_dump_json(indent=2)
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(serialized + "\n", encoding="utf-8")
        output(serialized)
        return 0 if report.passed else 1
    except Exception as error:
        output(
            json.dumps(
                {
                    "ok": False,
                    "message": "Gaia Test Kit could not run.",
                    "operator_action": "Check the dataset and --kit module:function factory.",
                    "issues": [str(error)],
                },
                sort_keys=True,
            )
        )
        return 2


def main(
    argv: Sequence[str] | None = None,
    *,
    output: Output = print,
    server_runner: ServerRunner = _default_server_runner,
    api_factory: ApiFactory = _default_api_factory,
    worker_runner: WorkerRunner = _default_worker_runner,
) -> int:
    """Run the Gaia CLI and return a process-style exit code."""
    args = build_parser().parse_args(argv)
    if hasattr(args, "config"):
        args.config = resolve_config_path(args.config)
    if args.command == "init":
        try:
            starters = selected_starters(
                args.template,
                tuple(args.component),
                tuple(args.starters),
            )
            _write_project(
                args.directory,
                args.name or args.directory.name,
                starters,
                template_id=args.template,
            )
        except ValueError as error:
            output(str(error))
            return 2
        output(
            f"initialized Gaia application in {args.directory} "
            f"with template {args.template} and starters: {', '.join(starters)}"
        )
        output(
            f"next: cd {args.directory} && uv sync -- installs this project so its "
            "scenarios.modules package is importable, which `gaia check` and `gaia dev` "
            "both require"
        )
        return 0
    if args.command == "add-workflow":
        try:
            targets = _write_workflow(args.directory, args.name)
        except ValueError as error:
            output(str(error))
            return 2
        output("created workflow files: " + ", ".join(str(item) for item in targets))
        return 0
    if args.command == "check":
        return _check(args.config, _config_overrides(args), output)
    if args.command == "doctor":
        return _doctor(args.config, _config_overrides(args), output)
    if args.command == "starters":
        return _starters(output)
    if args.command == "prompt":
        return _prompt(args, output)
    if args.command == "migrate":
        return _migrate(args.config, _config_overrides(args), args.revision, output)
    if args.command == "test":
        return _test(
            args.dataset,
            args.kit,
            args.repetitions,
            args.subject,
            args.output,
            output,
        )
    if args.command == "worker":
        return _worker(
            args.config,
            _config_overrides(args),
            args.app_target,
            worker_runner,
            output,
        )
    return _dev(
        args.config,
        _config_overrides(args),
        args.host,
        args.port,
        args.app_target,
        args.reload,
        server_runner,
        api_factory,
    )


if __name__ == "__main__":
    raise SystemExit(main())
