"""Application-facing contracts for document ingestion and cited retrieval."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DocumentAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    public: bool = False
    allowed_roles: tuple[str, ...] = ()
    allowed_user_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def has_audience(self) -> DocumentAccess:
        if not self.public and not self.allowed_roles and not self.allowed_user_ids:
            raise ValueError("a non-public document requires an allowed role or user")
        return self


class DocumentSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    tenant_id: str
    corpus_id: str
    version: str
    uri: str
    media_type: str
    access: DocumentAccess
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_identifiers(self) -> DocumentSource:
        for name in ("document_id", "tenant_id", "corpus_id", "version"):
            if _IDENTIFIER.fullmatch(str(getattr(self, name))) is None:
                raise ValueError(f"{name} contains unsupported characters")
        return self


class LoadedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DocumentSource
    content: bytes


class ParsedSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    section: str | None = None
    page_number: int | None = Field(default=None, ge=1)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DocumentSource
    sections: tuple[ParsedSection, ...]
    parser_id: str
    parser_version: str


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    document_version: str
    ordinal: int = Field(ge=0)
    text: str
    content_hash: str
    section: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_version: str
    source_uri: str
    chunk_id: str
    content_hash: str
    section: str | None = None
    page_number: int | None = None
    start_offset: int
    end_offset: int
    permission_basis: str


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    score: float | None = None
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    corpus_id: str
    query: str = Field(min_length=1)
    user_id: str
    roles: tuple[str, ...] = ()
    limit: int = Field(default=5, ge=1, le=50)


class IngestionStatus(StrEnum):
    CREATED = "created"
    REPLACED = "replaced"
    UNCHANGED = "unchanged"
    DELETED = "deleted"
    NOT_FOUND = "not_found"


class IngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_version: str | None
    status: IngestionStatus
    content_hash: str | None = None
    chunk_count: int = 0


class DocumentLoader(Protocol):
    async def load(self, source: DocumentSource) -> LoadedDocument: ...


class DocumentParser(Protocol):
    async def parse(self, document: LoadedDocument) -> ParsedDocument: ...


class Chunker(Protocol):
    chunker_id: str
    chunker_version: str

    def chunk(self, document: ParsedDocument) -> tuple[DocumentChunk, ...]: ...


class Retriever(Protocol):
    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]: ...
