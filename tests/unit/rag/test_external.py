from __future__ import annotations

import json

import httpx
import pytest

from gaia.rag.external import ExternalHttpRetriever, ExternalRagError
from gaia.spi.rag import RetrievalRequest


def request() -> RetrievalRequest:
    return RetrievalRequest(
        tenant_id="tenant-a",
        corpus_id="policies",
        query="annual leave",
        user_id="alice",
        roles=("employee",),
        limit=3,
    )


def hit(permission_basis: str = "role:employee") -> dict[str, object]:
    return {
        "text": "Employees receive ten days of annual leave.",
        "score": 0.92,
        "citation": {
            "document_id": "leave-policy",
            "document_version": "2026-01",
            "source_uri": "kb://hr/leave-policy",
            "chunk_id": "leave-policy-3",
            "content_hash": "sha256:abc",
            "section": "Annual leave",
            "page_number": 4,
            "start_offset": 120,
            "end_offset": 164,
            "permission_basis": permission_basis,
        },
        "metadata": {"department": "hr"},
    }


async def test_external_retriever_forwards_identity_and_returns_citations() -> None:
    async def handler(incoming: httpx.Request) -> httpx.Response:
        assert incoming.url.path == "/v1/retrieve"
        assert incoming.headers["authorization"] == "Bearer secret"
        payload = json.loads(incoming.content)
        assert payload["tenant_id"] == "tenant-a"
        assert payload["user_id"] == "alice"
        assert payload["roles"] == ["employee"]
        return httpx.Response(200, json={"hits": [hit()]})

    retriever = ExternalHttpRetriever(
        base_url="https://knowledge.example.com",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    )

    hits = await retriever.retrieve(request())

    assert hits[0].citation.document_id == "leave-policy"
    assert hits[0].citation.permission_basis == "role:employee"


async def test_external_retriever_rejects_permission_basis_outside_run_identity() -> None:
    retriever = ExternalHttpRetriever(
        base_url="https://knowledge.example.com",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"hits": [hit("role:finance")]})
        ),
    )

    with pytest.raises(ExternalRagError, match="EXTERNAL_RAG_PERMISSION_MISMATCH"):
        await retriever.retrieve(request())
