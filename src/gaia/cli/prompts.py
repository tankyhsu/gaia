"""Prompt Registry CLI operations with explicit quality evidence."""

from __future__ import annotations

import difflib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml

from gaia.config import GaiaApplicationConfig, resolve_secret
from gaia.contracts.models import RunMode
from gaia.integrations.prompt_postgres import PostgresPromptRegistry
from gaia.persistence.database import session_factory_resource
from gaia.spi.prompt import PromptArtifact, PromptRef, PromptValidation
from gaia.testing.models import TestReport


def load_prompt_artifact(path: Path) -> PromptArtifact:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("prompt artifact must contain a YAML mapping")
    return PromptArtifact.model_validate(raw)


def validation_from_report(path: Path, artifact: PromptArtifact) -> PromptValidation:
    report = TestReport.model_validate_json(path.read_text(encoding="utf-8"))
    expected = {
        "prompt_id": artifact.prompt_id,
        "prompt_version": artifact.version,
        "prompt_content_hash": artifact.content_hash,
    }
    mismatches = {
        key: {"expected": value, "actual": report.subject.get(key)}
        for key, value in expected.items()
        if report.subject.get(key) != value
    }
    if mismatches:
        raise ValueError(f"prompt test report subject mismatch: {mismatches}")
    if not report.passed:
        raise ValueError("prompt test report did not pass")
    return PromptValidation(
        passed=True,
        dataset_id=report.dataset_id,
        dataset_version=report.dataset_version,
        report_id=report.run_id,
        gate_ids=tuple(gate.gate_id for gate in report.gates if gate.passed),
        details={
            "repetitions": report.repetitions,
            "finished_at": report.finished_at.isoformat(),
        },
    )


async def execute_prompt_command(
    config: GaiaApplicationConfig,
    *,
    command: str,
    actor: str,
    artifact_path: Path | None = None,
    report_path: Path | None = None,
    prompt_id: str | None = None,
    version: str | None = None,
    environment: RunMode | None = None,
) -> dict[str, Any]:
    async with _registry(config) as registry:
        if command == "import":
            artifact = _required_artifact(artifact_path)
            imported = await registry.import_draft(artifact, actor=actor)
            return imported.model_dump(mode="json")
        if command == "diff":
            artifact = _required_artifact(artifact_path)
            registered = await registry.resolve(artifact.ref)
            return {
                "changed": registered.content_hash != artifact.content_hash,
                "registered": registered.version_id,
                "candidate": artifact.version_id,
                "diff": _artifact_diff(registered, artifact),
            }
        ref = PromptRef(
            prompt_id=_required("prompt_id", prompt_id),
            version=_required("version", version),
        )
        if command == "validate":
            if report_path is None:
                raise ValueError("report path is required")
            artifact = await registry.resolve(ref)
            evidence = validation_from_report(report_path, artifact)
            validated = await registry.validate(ref, evidence, actor=actor)
            return validated.model_dump(mode="json")
        if command == "publish":
            if environment is None:
                raise ValueError("environment is required")
            published = await registry.publish(ref, environment, actor=actor)
            return published.model_dump(mode="json")
        if command == "rollback":
            if environment is None:
                raise ValueError("environment is required")
            rolled_back = await registry.rollback(
                ref.prompt_id,
                environment,
                ref.version or "",
                actor=actor,
            )
            return rolled_back.model_dump(mode="json")
        raise ValueError(f"unsupported prompt command: {command}")


@asynccontextmanager
async def _registry(
    config: GaiaApplicationConfig,
) -> AsyncIterator[PostgresPromptRegistry]:
    if config.prompt.provider != "postgres":
        raise ValueError("prompt lifecycle commands require prompt.provider=postgres")
    operational = config.stores.operational
    async with session_factory_resource(
        resolve_secret(config.runtime.database_url),
        pool_size=operational.pool_size,
        max_overflow=operational.max_overflow,
        pool_timeout_seconds=operational.pool_timeout_seconds,
        pool_recycle_seconds=operational.pool_recycle_seconds,
        auto_create=False,
    ) as factory:
        yield PostgresPromptRegistry(factory)


def _required_artifact(path: Path | None) -> PromptArtifact:
    if path is None:
        raise ValueError("artifact path is required")
    return load_prompt_artifact(path)


def _required(name: str, value: str | None) -> str:
    if value is None:
        raise ValueError(f"{name} is required")
    return value


def _artifact_diff(current: PromptArtifact, candidate: PromptArtifact) -> str:
    current_yaml = yaml.safe_dump(
        current.model_dump(mode="json"),
        sort_keys=True,
        allow_unicode=True,
    ).splitlines()
    candidate_yaml = yaml.safe_dump(
        candidate.model_dump(mode="json"),
        sort_keys=True,
        allow_unicode=True,
    ).splitlines()
    return "\n".join(
        difflib.unified_diff(
            current_yaml,
            candidate_yaml,
            fromfile=current.version_id,
            tofile=candidate.version_id,
            lineterm="",
        )
    )


def prompt_result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
