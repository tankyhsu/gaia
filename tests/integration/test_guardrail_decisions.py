from pathlib import Path

from gaia.guardrails import GuardrailPipeline, PatternGuardrail, PatternRule
from gaia.guardrails.store import SqlAlchemyGuardrailDecisionStore
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.spi.guardrail import GuardrailAction, GuardrailContext, GuardrailStage


async def test_guardrail_decisions_persist_without_content(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/guardrails.db"
    factory = await initialize_database(database_url)
    store = SqlAlchemyGuardrailDecisionStore(factory)
    pipeline = GuardrailPipeline(
        (
            PatternGuardrail(
                "pii",
                (
                    PatternRule(
                        pattern="private-value",
                        code="PII_REDACTED",
                        action=GuardrailAction.REWRITE,
                    ),
                ),
            ),
        ),
        sink=store,
    )
    try:
        output = await pipeline.evaluate(
            "private-value",
            GuardrailContext(
                stage=GuardrailStage.RETRIEVAL,
                run_id="run-guardrail",
                scenario_id="knowledge-search",
            ),
        )
        projection = await store.for_run("run-guardrail")

        assert output == "[REDACTED]"
        assert projection.summary.total == 1
        assert projection.summary.rewritten == 1
        assert projection.summary.by_stage == {"retrieval": 1}
        assert "private-value" not in projection.model_dump_json()
    finally:
        await dispose_session_factory(factory)
