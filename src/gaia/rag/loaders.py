"""Reference document loaders; applications may replace them."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote, urlparse

from gaia.spi.rag import DocumentSource, LoadedDocument


class LocalFileDocumentLoader:
    """Load files below one configured root without allowing path escape."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    async def load(self, source: DocumentSource) -> LoadedDocument:
        parsed = urlparse(source.uri)
        if parsed.scheme not in {"", "file"}:
            raise ValueError("DOCUMENT_LOADER_URI_UNSUPPORTED")
        raw_path = unquote(parsed.path if parsed.scheme == "file" else source.uri)
        candidate = Path(raw_path).expanduser()
        path = (
            candidate.resolve() if candidate.is_absolute() else (self._root / candidate).resolve()
        )
        if not path.is_relative_to(self._root):
            raise PermissionError("DOCUMENT_PATH_OUTSIDE_ROOT")
        if not path.is_file():
            raise FileNotFoundError(path)
        return LoadedDocument(
            source=source,
            content=await asyncio.to_thread(path.read_bytes),
        )
