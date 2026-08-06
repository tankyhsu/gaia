from examples.controlled_task.context import MockContextProvider
from gaia.spi.context import ContextQuery, RunSession


async def test_mock_context_returns_versioned_evidence() -> None:
    context = await MockContextProvider().get_context(
        session=RunSession(run_id="r", user_id="u", organization="org-alpha", roles=["reader"]),
        query=ContextQuery(organization="org-alpha"),
    )
    assert context.documents[0].source_id == "evidence-controlled-task"
    assert context.gaps == []
