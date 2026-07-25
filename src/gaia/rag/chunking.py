"""Deterministic reference chunker with stable content identities."""

from __future__ import annotations

import hashlib
import json

from gaia.sdk.rag import DocumentChunk, ParsedDocument


class FixedWindowChunker:
    chunker_id = "fixed-window"
    chunker_version = "1.0.0"

    def __init__(self, *, chunk_size: int = 1200, overlap: int = 120) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be non-negative and smaller than chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def chunk(self, document: ParsedDocument) -> tuple[DocumentChunk, ...]:
        chunks: list[DocumentChunk] = []
        ordinal = 0
        for section in document.sections:
            start = 0
            text = section.text
            while start < len(text):
                end = min(len(text), start + self._chunk_size)
                content = text[start:end].strip()
                if content:
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    source_hash = hashlib.sha256(
                        json.dumps(
                            document.source.model_dump(mode="json"),
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest()
                    identity = (
                        f"{source_hash}:{document.parser_id}:{document.parser_version}:"
                        f"{self.chunker_id}:{self.chunker_version}:{ordinal}:{digest}"
                    )
                    chunks.append(
                        DocumentChunk(
                            chunk_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                            document_id=document.source.document_id,
                            document_version=document.source.version,
                            ordinal=ordinal,
                            text=content,
                            content_hash=digest,
                            section=section.section,
                            page_number=section.page_number,
                            start_offset=start,
                            end_offset=end,
                        )
                    )
                    ordinal += 1
                if end == len(text):
                    break
                start = end - self._overlap
        if not chunks:
            raise ValueError("DOCUMENT_CHUNKS_EMPTY")
        return tuple(chunks)
