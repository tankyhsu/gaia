from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from gaia.rag import FixedWindowChunker, MemoryRagRepository, RagPipeline, Utf8TextParser
from gaia.spi.memory import MemoryItem
from gaia.spi.rag import (
    DocumentAccess,
    DocumentSource,
    IngestionStatus,
    LoadedDocument,
    RetrievalRequest,
)


class MutableLoader:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    async def load(self, source: DocumentSource) -> LoadedDocument:
        self.calls += 1
        return LoadedDocument(source=source, content=self.content)


class InMemoryStore:
    def __init__(self) -> None:
        self.values: dict[tuple[tuple[str, ...], str], MemoryItem] = {}
        self.put_count = 0

    async def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        *,
        index: list[str] | bool | None = None,
    ) -> None:
        del index
        now = datetime.now(UTC)
        current = self.values.get((namespace, key))
        self.values[(namespace, key)] = MemoryItem(
            namespace=namespace,
            key=key,
            value=value,
            created_at=now if current is None else current.created_at,
            updated_at=now,
        )
        self.put_count += 1

    async def get(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None:
        return self.values.get((namespace, key))

    async def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[MemoryItem]:
        del filters
        terms = set((query or "").lower().split())
        items: list[MemoryItem] = []
        for (namespace, _), item in self.values.items():
            if namespace[: len(namespace_prefix)] != namespace_prefix:
                continue
            text = str(item.value.get("text", "")).lower()
            score = float(sum(term in text for term in terms))
            items.append(item.model_copy(update={"score": score}))
        items.sort(key=lambda item: item.score or 0, reverse=True)
        return items[offset : offset + limit]

    async def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self.values.pop((namespace, key), None)


class FailOnceDeleteStore(InMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_delete = False

    async def delete(self, namespace: tuple[str, ...], key: str) -> None:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("temporary cleanup failure")
        await super().delete(namespace, key)


def source(
    *,
    version: str = "1.0.0",
    roles: tuple[str, ...] = ("finance",),
    tenant_id: str = "tenant-a",
) -> DocumentSource:
    return DocumentSource(
        document_id="expense-policy",
        tenant_id=tenant_id,
        corpus_id="policies",
        version=version,
        uri="expense-policy.md",
        media_type="text/markdown",
        access=DocumentAccess(allowed_roles=roles),
        metadata={"department": "finance"},
    )


def pipeline(loader: MutableLoader, store: InMemoryStore) -> RagPipeline:
    return RagPipeline(
        loader,
        Utf8TextParser(),
        FixedWindowChunker(chunk_size=48, overlap=8),
        MemoryRagRepository(store, candidate_multiplier=10),
    )


async def test_ingestion_is_idempotent_and_returns_cited_authorized_results() -> None:
    loader = MutableLoader(
        b"Employees submit an invoice within 30 days. Manager approval is required."
    )
    store = InMemoryStore()
    rag = pipeline(loader, store)

    created = await rag.ingest(source())
    writes_after_create = store.put_count
    unchanged = await rag.ingest(source())
    authorized = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="invoice",
            user_id="alice",
            roles=("finance",),
        )
    )
    unauthorized = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="invoice",
            user_id="bob",
            roles=("engineering",),
        )
    )

    assert created.status == IngestionStatus.CREATED
    assert unchanged.status == IngestionStatus.UNCHANGED
    assert store.put_count == writes_after_create
    assert authorized[0].citation.document_version == "1.0.0"
    assert authorized[0].citation.source_uri == "expense-policy.md"
    assert authorized[0].citation.permission_basis == "role:finance"
    assert unauthorized == ()


async def test_replacement_and_delete_never_return_inactive_generation() -> None:
    loader = MutableLoader(b"Old travel policy requires paper receipts.")
    store = InMemoryStore()
    rag = pipeline(loader, store)
    await rag.ingest(source())

    loader.content = b"New travel policy accepts digital receipts only."
    replaced = await rag.ingest(source(version="2.0.0"))
    old_results = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="paper",
            user_id="alice",
            roles=("finance",),
        )
    )
    new_results = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="digital",
            user_id="alice",
            roles=("finance",),
        )
    )
    deleted = await rag.delete(
        tenant_id="tenant-a",
        corpus_id="policies",
        document_id="expense-policy",
    )
    after_delete = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="digital",
            user_id="alice",
            roles=("finance",),
        )
    )

    assert replaced.status == IngestionStatus.REPLACED
    assert all(item.citation.document_version == "2.0.0" for item in old_results)
    assert new_results[0].citation.document_version == "2.0.0"
    assert deleted.status == IngestionStatus.DELETED
    assert after_delete == ()


async def test_namespace_isolates_tenants_even_with_the_same_document_id() -> None:
    loader = MutableLoader(b"Tenant specific policy.")
    store = InMemoryStore()
    rag = pipeline(loader, store)
    await rag.ingest(source(tenant_id="tenant-a"))
    await rag.ingest(source(tenant_id="tenant-b"))

    tenant_a = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="policy",
            user_id="alice",
            roles=("finance",),
        )
    )
    assert len(tenant_a) == 1


async def test_retried_replacement_finishes_pending_old_chunk_cleanup() -> None:
    loader = MutableLoader(b"Old policy.")
    store = FailOnceDeleteStore()
    rag = pipeline(loader, store)
    await rag.ingest(source())
    loader.content = b"New policy."
    replacement = source(version="2.0.0")
    store.fail_next_delete = True

    with pytest.raises(RuntimeError, match="temporary cleanup failure"):
        await rag.ingest(replacement)
    retried = await rag.ingest(replacement)
    manifest = await MemoryRagRepository(store).manifest(
        tenant_id="tenant-a",
        corpus_id="policies",
        document_id="expense-policy",
    )

    assert retried.status == IngestionStatus.UNCHANGED
    assert manifest is not None
    assert manifest.pending_delete_keys == ()


async def test_retried_delete_keeps_cleanup_pointer_but_hides_document() -> None:
    loader = MutableLoader(b"Policy to delete.")
    store = FailOnceDeleteStore()
    rag = pipeline(loader, store)
    await rag.ingest(source())
    store.fail_next_delete = True

    with pytest.raises(RuntimeError, match="temporary cleanup failure"):
        await rag.delete(
            tenant_id="tenant-a",
            corpus_id="policies",
            document_id="expense-policy",
        )
    hidden = await rag.retrieve(
        RetrievalRequest(
            tenant_id="tenant-a",
            corpus_id="policies",
            query="policy",
            user_id="alice",
            roles=("finance",),
        )
    )
    retried = await rag.delete(
        tenant_id="tenant-a",
        corpus_id="policies",
        document_id="expense-policy",
    )

    assert hidden == ()
    assert retried.status == IngestionStatus.DELETED
