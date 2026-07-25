"""Small text parser reference implementation."""

from __future__ import annotations

from gaia.sdk.rag import LoadedDocument, ParsedDocument, ParsedSection

_TEXT_MEDIA_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}


class Utf8TextParser:
    parser_id = "utf8-text"
    parser_version = "1.0.0"

    async def parse(self, document: LoadedDocument) -> ParsedDocument:
        if document.source.media_type not in _TEXT_MEDIA_TYPES:
            raise ValueError("DOCUMENT_PARSER_MEDIA_TYPE_UNSUPPORTED")
        try:
            text = document.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("DOCUMENT_ENCODING_UNSUPPORTED") from error
        if not text.strip():
            raise ValueError("DOCUMENT_CONTENT_EMPTY")
        return ParsedDocument(
            source=document.source,
            sections=(ParsedSection(text=text),),
            parser_id=self.parser_id,
            parser_version=self.parser_version,
        )
