"""MemoryStore-backed active-generation repository for cited retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from gaia.sdk.memory import MemoryItem, MemoryStore
from gaia.sdk.rag import (
    Citation,
    DocumentAccess,
    DocumentChunk,
    DocumentSource,
    RetrievalHit,
    RetrievalRequest,
)


class DocumentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DocumentSource
    document_content_hash: str
    generation_id: str
    chunk_keys: tuple[str, ...]
    parser_id: str
    parser_version: str
    chunker_id: str
    chunker_version: str
    pending_delete_keys: tuple[str, ...] = ()
    active: bool = True


class MemoryRagRepository:
    """Use a manifest pointer to keep retrieval consistent during replacement."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        namespace_prefix: str = "gaia-rag",
        candidate_multiplier: int = 4,
    ) -> None:
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be positive")
        self._store = store
        self._prefix = namespace_prefix
        self._candidate_multiplier = candidate_multiplier

    async def manifest(
        self,
        *,
        tenant_id: str,
        corpus_id: str,
        document_id: str,
    ) -> DocumentManifest | None:
        item = await self._store.get(
            self._manifest_namespace(tenant_id, corpus_id),
            document_id,
        )
        return None if item is None else DocumentManifest.model_validate(item.value)

    async def activate(
        self,
        manifest: DocumentManifest,
        chunks: tuple[DocumentChunk, ...],
    ) -> None:
        source = manifest.source
        chunk_namespace = self._chunk_namespace(source.tenant_id, source.corpus_id)
        staged: list[str] = []
        try:
            for chunk in chunks:
                await self._store.put(
                    chunk_namespace,
                    chunk.chunk_id,
                    _chunk_value(chunk, manifest),
                    index=["text"],
                )
                staged.append(chunk.chunk_id)
        except Exception:
            for key in staged:
                await self._store.delete(chunk_namespace, key)
            raise

        previous = await self.manifest(
            tenant_id=source.tenant_id,
            corpus_id=source.corpus_id,
            document_id=source.document_id,
        )
        pending_delete_keys = (
            ()
            if previous is None
            else tuple(key for key in previous.chunk_keys if key not in manifest.chunk_keys)
        )
        active_manifest = manifest.model_copy(update={"pending_delete_keys": pending_delete_keys})
        await self._store.put(
            self._manifest_namespace(source.tenant_id, source.corpus_id),
            source.document_id,
            active_manifest.model_dump(mode="json"),
            index=False,
        )
        if pending_delete_keys:
            await self.cleanup(active_manifest)

    async def cleanup(self, manifest: DocumentManifest) -> DocumentManifest:
        if not manifest.pending_delete_keys:
            return manifest
        source = manifest.source
        for key in manifest.pending_delete_keys:
            await self._store.delete(
                self._chunk_namespace(source.tenant_id, source.corpus_id),
                key,
            )
        cleaned = manifest.model_copy(update={"pending_delete_keys": ()})
        await self._store.put(
            self._manifest_namespace(source.tenant_id, source.corpus_id),
            source.document_id,
            cleaned.model_dump(mode="json"),
            index=False,
        )
        return cleaned

    async def delete(
        self,
        *,
        tenant_id: str,
        corpus_id: str,
        document_id: str,
    ) -> DocumentManifest | None:
        manifest = await self.manifest(
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            document_id=document_id,
        )
        if manifest is None:
            return None
        deleting = manifest.model_copy(update={"active": False})
        await self._store.put(
            self._manifest_namespace(tenant_id, corpus_id),
            document_id,
            deleting.model_dump(mode="json"),
            index=False,
        )
        for key in (*deleting.chunk_keys, *deleting.pending_delete_keys):
            await self._store.delete(self._chunk_namespace(tenant_id, corpus_id), key)
        await self._store.delete(
            self._manifest_namespace(tenant_id, corpus_id),
            document_id,
        )
        return deleting

    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        candidates = await self._store.search(
            self._chunk_namespace(request.tenant_id, request.corpus_id),
            query=request.query,
            limit=request.limit * self._candidate_multiplier,
        )
        manifests: dict[str, DocumentManifest | None] = {}
        hits: list[RetrievalHit] = []
        for item in candidates:
            document_id = str(item.value["document_id"])
            if document_id not in manifests:
                manifests[document_id] = await self.manifest(
                    tenant_id=request.tenant_id,
                    corpus_id=request.corpus_id,
                    document_id=document_id,
                )
            manifest = manifests[document_id]
            if (
                manifest is None
                or not manifest.active
                or item.value.get("generation_id") != manifest.generation_id
            ):
                continue
            permission_basis = _permission_basis(manifest.source.access, request)
            if permission_basis is None:
                continue
            hits.append(_hit(item, manifest, permission_basis))
            if len(hits) == request.limit:
                break
        return tuple(hits)

    def _manifest_namespace(self, tenant_id: str, corpus_id: str) -> tuple[str, ...]:
        return (self._prefix, tenant_id, corpus_id, "documents")

    def _chunk_namespace(self, tenant_id: str, corpus_id: str) -> tuple[str, ...]:
        return (self._prefix, tenant_id, corpus_id, "chunks")


def _chunk_value(
    chunk: DocumentChunk,
    manifest: DocumentManifest,
) -> dict[str, Any]:
    source = manifest.source
    return {
        **chunk.model_dump(mode="json"),
        "generation_id": manifest.generation_id,
        "source_uri": source.uri,
        "access": source.access.model_dump(mode="json"),
        "metadata": source.metadata,
    }


def _permission_basis(
    access: DocumentAccess,
    request: RetrievalRequest,
) -> str | None:
    if access.public:
        return "public"
    if request.user_id in access.allowed_user_ids:
        return f"user:{request.user_id}"
    matched_roles = sorted(set(request.roles).intersection(access.allowed_roles))
    return f"role:{matched_roles[0]}" if matched_roles else None


def _hit(
    item: MemoryItem,
    manifest: DocumentManifest,
    permission_basis: str,
) -> RetrievalHit:
    value = item.value
    return RetrievalHit(
        text=str(value["text"]),
        score=item.score,
        citation=Citation(
            document_id=manifest.source.document_id,
            document_version=manifest.source.version,
            source_uri=manifest.source.uri,
            chunk_id=str(value["chunk_id"]),
            content_hash=str(value["content_hash"]),
            section=value.get("section"),
            page_number=value.get("page_number"),
            start_offset=int(value["start_offset"]),
            end_offset=int(value["end_offset"]),
            permission_basis=permission_basis,
        ),
        metadata=dict(manifest.source.metadata),
    )
