from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gaia.rag import FixedWindowChunker, MemoryRagRepository, RagPipeline, Utf8TextParser
from gaia.spi.memory import MemoryItem
from gaia.spi.rag import (
    DocumentAccess,
    DocumentSource,
    LoadedDocument,
    RetrievalRequest,
)

DATASET = Path(__file__).parents[2] / "examples" / "rag_minimal" / "specs" / "golden-dataset.json"


class DatasetLoader:
    def __init__(self, content: dict[str, str]) -> None:
        self._content = content

    async def load(self, source: DocumentSource) -> LoadedDocument:
        return LoadedDocument(source=source, content=self._content[source.uri].encode())


class KeywordStore:
    def __init__(self) -> None:
        self._items: dict[tuple[tuple[str, ...], str], MemoryItem] = {}

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
        self._items[(namespace, key)] = MemoryItem(
            namespace=namespace,
            key=key,
            value=value,
            created_at=now,
            updated_at=now,
        )

    async def get(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None:
        return self._items.get((namespace, key))

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
        candidates = [
            item.model_copy(
                update={
                    "score": float(
                        sum(term in str(item.value.get("text", "")).lower() for term in terms)
                    )
                }
            )
            for (namespace, _), item in self._items.items()
            if namespace[: len(namespace_prefix)] == namespace_prefix
        ]
        candidates.sort(key=lambda item: item.score or 0, reverse=True)
        return candidates[offset : offset + limit]

    async def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self._items.pop((namespace, key), None)


async def test_minimal_cited_rag_golden_dataset() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    content = {item["uri"]: item["content"] for item in dataset["documents"]}
    pipeline = RagPipeline(
        DatasetLoader(content),
        Utf8TextParser(),
        FixedWindowChunker(chunk_size=256, overlap=32),
        MemoryRagRepository(KeywordStore(), candidate_multiplier=10),
    )
    for item in dataset["documents"]:
        await pipeline.ingest(
            DocumentSource(
                document_id=item["document_id"],
                tenant_id="example-tenant",
                corpus_id="policies",
                version=item["version"],
                uri=item["uri"],
                media_type="text/markdown",
                access=DocumentAccess(allowed_roles=tuple(item["allowed_roles"])),
            )
        )

    for case in dataset["cases"]:
        hits = await pipeline.retrieve(
            RetrievalRequest(
                tenant_id="example-tenant",
                corpus_id="policies",
                query=case["query"],
                user_id="dataset-user",
                roles=tuple(case["roles"]),
            )
        )
        assert [hit.citation.document_id for hit in hits] == case["expected_document_ids"]
        assert all(hit.citation.source_uri for hit in hits)
        assert all(hit.citation.document_version for hit in hits)
        assert all(hit.citation.permission_basis for hit in hits)
