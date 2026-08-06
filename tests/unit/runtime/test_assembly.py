from __future__ import annotations

import pytest

from gaia import PromptRef, ScenarioContext, scenario
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import RunMode
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.runtime.assembly import RuntimeAssembler, _normalize_guardrails
from gaia.runtime.in_process_runtime import InProcessRuntimeEngine
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.spi.guardrail import ContentGuardrail, GuardrailStage


@scenario("assembly.first")
async def _first(context: ScenarioContext) -> dict[str, object]:
    return {"run_id": context.run_id}


@scenario("assembly.first")
async def _second(context: ScenarioContext) -> dict[str, object]:
    return {"run_id": context.run_id}


async def _tool(**kwargs: object) -> dict[str, object]:
    return {}


def test_duplicate_scenario_id_raises() -> None:
    with pytest.raises(ValueError, match="duplicate scenario_id"):
        RuntimeAssembler(
            config=GaiaApplicationConfig(),
            scenario_handlers=(_first, _second),
            tool_handlers=(),
        )


def test_duplicate_tool_handler_raises() -> None:
    with pytest.raises(ValueError, match="duplicate tool handler"):
        RuntimeAssembler(
            config=GaiaApplicationConfig(),
            scenario_handlers=(),
            tool_handlers=(_tool, _tool),
        )


def test_prompt_ref_without_prompt_provider_raises() -> None:
    @scenario(
        "assembly.prompted",
        prompt=PromptRef(prompt_id="assembly-prompted", environment=RunMode.MOCK),
    )
    async def prompted(context: ScenarioContext) -> dict[str, object]:
        return {"run_id": context.run_id}

    with pytest.raises(ValueError, match="scenario PromptRef requires prompt_provider"):
        RuntimeAssembler(
            config=GaiaApplicationConfig(),
            scenario_handlers=(prompted,),
            tool_handlers=(),
        )


def test_partial_guardrails_mapping_is_normalized_to_every_stage() -> None:
    """A caller constructing RuntimeAssembler directly (e.g. a future Starter) may

    naturally pass a partial mapping covering only the stages it cares about.
    __post_init__ must complete it so create_engine's direct `stage_guardrails[stage]`
    indexing never raises KeyError for an unmentioned stage.
    """

    guardrail: ContentGuardrail = object()  # type: ignore[assignment]
    assembler = RuntimeAssembler(
        config=GaiaApplicationConfig(),
        scenario_handlers=(),
        tool_handlers=(),
        guardrails={GuardrailStage.INPUT: (guardrail,)},
    )

    assert assembler.guardrails is not None
    assert set(assembler.guardrails.keys()) == set(GuardrailStage)
    assert assembler.guardrails[GuardrailStage.INPUT] == (guardrail,)
    assert assembler.guardrails[GuardrailStage.OUTPUT] == ()
    assert assembler.guardrails[GuardrailStage.RETRIEVAL] == ()
    assert assembler.guardrails[GuardrailStage.TOOL_INPUT] == ()
    assert assembler.guardrails[GuardrailStage.TOOL_OUTPUT] == ()


def test_normalize_guardrails_is_idempotent() -> None:
    guardrail: ContentGuardrail = object()  # type: ignore[assignment]
    once = _normalize_guardrails({GuardrailStage.INPUT: (guardrail,)}, ())
    twice = _normalize_guardrails(once, ())

    assert twice == once
    assert set(twice.keys()) == set(GuardrailStage)


@pytest.mark.asyncio
async def test_temporal_provider_switch_returns_temporal_runtime() -> None:
    factory = await initialize_database("sqlite+aiosqlite:///:memory:")
    try:
        runtime = RuntimeAssembler(
            config=GaiaApplicationConfig(
                runtime={"execution": {"provider": "temporal"}}
            ),
            scenario_handlers=(),
            tool_handlers=(),
        ).create_engine(factory, "sqlite+aiosqlite:///:memory:")
        assert isinstance(runtime, TemporalRuntimeEngine)
    finally:
        await dispose_session_factory(factory)


@pytest.mark.asyncio
async def test_default_provider_returns_in_process_runtime() -> None:
    factory = await initialize_database("sqlite+aiosqlite:///:memory:")
    try:
        runtime = RuntimeAssembler(
            config=GaiaApplicationConfig(),
            scenario_handlers=(),
            tool_handlers=(),
        ).create_engine(factory, "sqlite+aiosqlite:///:memory:")
        assert isinstance(runtime, InProcessRuntimeEngine)
    finally:
        await dispose_session_factory(factory)


def test_legacy_persistent_execution_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        GaiaApplicationConfig(runtime={"execution": {"provider": "persistent"}})
