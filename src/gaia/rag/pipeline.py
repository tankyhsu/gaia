"""Minimal ingestion and cited retrieval orchestration."""

from __future__ import annotations

import hashlib
import json

from gaia.rag.repository import DocumentManifest, MemoryRagRepository
from gaia.sdk.rag import (
    Chunker,
    DocumentLoader,
    DocumentParser,
    DocumentSource,
    IngestionResult,
    IngestionStatus,
    RetrievalHit,
    RetrievalRequest,
)


class RagPipeline:
    def __init__(
        self,
        loader: DocumentLoader,
        parser: DocumentParser,
        chunker: Chunker,
        repository: MemoryRagRepository,
    ) -> None:
        self._loader = loader
        self._parser = parser
        self._chunker = chunker
        self._repository = repository

    async def ingest(self, source: DocumentSource) -> IngestionResult:
        loaded = await self._loader.load(source)
        if loaded.source != source:
            raise ValueError("DOCUMENT_LOADER_SOURCE_MISMATCH")
        document_hash = hashlib.sha256(loaded.content).hexdigest()
        parsed = await self._parser.parse(loaded)
        if parsed.source != source:
            raise ValueError("DOCUMENT_PARSER_SOURCE_MISMATCH")
        previous = await self._repository.manifest(
            tenant_id=source.tenant_id,
            corpus_id=source.corpus_id,
            document_id=source.document_id,
        )
        if previous is not None and previous.pending_delete_keys:
            previous = await self._repository.cleanup(previous)
        if (
            previous is not None
            and previous.active
            and previous.source == source
            and previous.document_content_hash == document_hash
            and previous.parser_id == parsed.parser_id
            and previous.parser_version == parsed.parser_version
            and previous.chunker_id == self._chunker.chunker_id
            and previous.chunker_version == self._chunker.chunker_version
        ):
            return IngestionResult(
                document_id=source.document_id,
                document_version=source.version,
                status=IngestionStatus.UNCHANGED,
                content_hash=document_hash,
                chunk_count=len(previous.chunk_keys),
            )

        chunks = self._chunker.chunk(parsed)
        source_hash = hashlib.sha256(
            json.dumps(
                source.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        generation_id = hashlib.sha256(
            (
                f"{source_hash}:{document_hash}:"
                f"{parsed.parser_id}:{parsed.parser_version}:"
                f"{self._chunker.chunker_id}:{self._chunker.chunker_version}"
            ).encode()
        ).hexdigest()
        manifest = DocumentManifest(
            source=source,
            document_content_hash=document_hash,
            generation_id=generation_id,
            chunk_keys=tuple(chunk.chunk_id for chunk in chunks),
            parser_id=parsed.parser_id,
            parser_version=parsed.parser_version,
            chunker_id=self._chunker.chunker_id,
            chunker_version=self._chunker.chunker_version,
        )
        await self._repository.activate(manifest, chunks)
        return IngestionResult(
            document_id=source.document_id,
            document_version=source.version,
            status=(IngestionStatus.CREATED if previous is None else IngestionStatus.REPLACED),
            content_hash=document_hash,
            chunk_count=len(chunks),
        )

    async def delete(
        self,
        *,
        tenant_id: str,
        corpus_id: str,
        document_id: str,
    ) -> IngestionResult:
        deleted = await self._repository.delete(
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            document_id=document_id,
        )
        return IngestionResult(
            document_id=document_id,
            document_version=None if deleted is None else deleted.source.version,
            status=(IngestionStatus.NOT_FOUND if deleted is None else IngestionStatus.DELETED),
            content_hash=None if deleted is None else deleted.document_content_hash,
            chunk_count=0 if deleted is None else len(deleted.chunk_keys),
        )

    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        return await self._repository.retrieve(request)
