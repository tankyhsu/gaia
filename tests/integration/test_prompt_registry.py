from pathlib import Path

import pytest

from gaia.contracts.models import RunMode
from gaia.integrations.prompt_postgres import (
    PostgresPromptRegistry,
    PromptRegistryConflict,
)
from gaia.persistence.database import initialize_database
from gaia.sdk.prompt import (
    PromptArtifact,
    PromptLifecycleStatus,
    PromptRef,
    PromptValidation,
)


def artifact(version: str, instruction: str) -> PromptArtifact:
    return PromptArtifact(
        prompt_id="summary",
        version=version,
        messages=(
            {"role": "system", "content": instruction},
            {"role": "user", "content": "{text}"},
        ),
    )


def evidence(version: str) -> PromptValidation:
    return PromptValidation(
        passed=True,
        dataset_id="summary-golden",
        dataset_version="3",
        report_id=f"report-{version}",
        gate_ids=("pass-rate",),
    )


async def validated(
    registry: PostgresPromptRegistry,
    value: PromptArtifact,
) -> None:
    await registry.import_draft(value, actor="developer")
    result = await registry.validate(
        value.ref,
        evidence(value.version),
        actor="qa",
    )
    assert result.status == PromptLifecycleStatus.VALIDATING


async def test_registry_publishes_rolls_back_and_preserves_exact_versions(
    tmp_path: Path,
) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/registry.db")
    registry = PostgresPromptRegistry(factory)
    first = artifact("1.0.0", "Summarize factually.")
    second = artifact("2.0.0", "Summarize factually in three bullets.")
    await validated(registry, first)
    await validated(registry, second)

    first_release = await registry.publish(
        first.ref,
        RunMode.CUSTOMER,
        actor="release-manager",
    )
    resolved_first = await registry.resolve(
        PromptRef(prompt_id="summary", environment=RunMode.CUSTOMER)
    )
    second_release = await registry.publish(
        second.ref,
        RunMode.CUSTOMER,
        actor="release-manager",
    )
    resolved_second = await registry.resolve(
        PromptRef(prompt_id="summary", environment=RunMode.CUSTOMER)
    )

    assert first_release.version == resolved_first.version == "1.0.0"
    assert second_release.version == resolved_second.version == "2.0.0"
    assert (await registry.resolve(first.ref)).content_hash == first.content_hash

    rolled_back = await registry.rollback(
        "summary",
        RunMode.CUSTOMER,
        "1.0.0",
        actor="release-manager",
    )
    assert rolled_back.version == "1.0.0"
    assert (
        await registry.resolve(PromptRef(prompt_id="summary", environment=RunMode.CUSTOMER))
    ).version == "1.0.0"


async def test_registry_enforces_immutability_quality_and_retirement(
    tmp_path: Path,
) -> None:
    factory = await initialize_database(f"sqlite+aiosqlite:///{tmp_path}/registry.db")
    registry = PostgresPromptRegistry(factory)
    first = artifact("1.0.0", "Summarize factually.")
    await registry.import_draft(first, actor="developer")

    with pytest.raises(PromptRegistryConflict, match="IMMUTABLE"):
        await registry.import_draft(
            artifact("1.0.0", "Changed in place."),
            actor="developer",
        )
    with pytest.raises(PromptRegistryConflict, match="QUALITY_GATE_FAILED"):
        await registry.validate(
            first.ref,
            evidence("1.0.0").model_copy(update={"passed": False}),
            actor="qa",
        )
    with pytest.raises(PromptRegistryConflict, match="NOT_VALIDATED"):
        await registry.publish(first.ref, RunMode.CUSTOMER, actor="release-manager")

    await registry.validate(first.ref, evidence("1.0.0"), actor="qa")
    await registry.publish(first.ref, RunMode.CUSTOMER, actor="release-manager")
    with pytest.raises(PromptRegistryConflict, match="STILL_RELEASED"):
        await registry.retire(first.ref, actor="developer")

    second = artifact("2.0.0", "Summarize in three bullets.")
    await validated(registry, second)
    await registry.publish(second.ref, RunMode.CUSTOMER, actor="release-manager")
    retired = await registry.retire(first.ref, actor="developer")

    assert retired.status == PromptLifecycleStatus.RETIRED
    assert (await registry.resolve(first.ref)).version == "1.0.0"
