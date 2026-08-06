from __future__ import annotations

import pytest

from gaia import Citation, RetrievalHit, RetrievalRequest
from gaia.contracts.models import ErrorCode, RunRequest
from gaia.runtime.retrieval import ScopedRetriever
from gaia.runtime.tool_execution import ToolExecutionError


async def test_scoped_retriever_rejects_identity_substitution_before_adapter_call() -> None:
    calls = 0

    class RetrieverStub:
        async def retrieve(
            self,
            request: RetrievalRequest,
        ) -> tuple[RetrievalHit, ...]:
            nonlocal calls
            calls += 1
            return (
                RetrievalHit(
                    text=request.query,
                    citation=Citation(
                        document_id="handbook",
                        document_version="1",
                        source_uri="memory://handbook",
                        chunk_id="handbook:0",
                        content_hash="a" * 64,
                        start_offset=0,
                        end_offset=len(request.query),
                        permission_basis="role:employee",
                    ),
                ),
            )

    run_request = RunRequest.model_validate(
        {
            "scenario_id": "knowledge.search",
            "mode": "mock",
            "user": {
                "id": "employee-1",
                "organization": "tenant-a",
                "roles": ["employee"],
            },
            "request": {"text": "annual leave"},
        }
    )
    retriever = ScopedRetriever(
        RetrieverStub(),
        run_id="run-1",
        request=run_request,
    )

    hits = await retriever.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="handbook",
            query="annual leave",
            user_id="employee-1",
            roles=("employee",),
        )
    )
    with pytest.raises(ToolExecutionError) as captured:
        await retriever.retrieve(
            RetrievalRequest(
                tenant_id="tenant-b",
                corpus_id="handbook",
                query="annual leave",
                user_id="employee-1",
                roles=("employee",),
            )
        )

    assert hits[0].citation.document_id == "handbook"
    assert captured.value.code == ErrorCode.FORBIDDEN
    assert calls == 1
