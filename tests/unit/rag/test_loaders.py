from pathlib import Path

import pytest

from gaia.rag import LocalFileDocumentLoader
from gaia.sdk.rag import DocumentAccess, DocumentSource


def source(uri: str) -> DocumentSource:
    return DocumentSource(
        document_id="handbook",
        tenant_id="tenant",
        corpus_id="policies",
        version="1",
        uri=uri,
        media_type="text/plain",
        access=DocumentAccess(public=True),
    )


async def test_local_loader_reads_below_root_and_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    (root / "handbook.txt").write_text("Policy", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("Secret", encoding="utf-8")
    loader = LocalFileDocumentLoader(root)

    loaded = await loader.load(source("handbook.txt"))
    assert loaded.content == b"Policy"
    with pytest.raises(PermissionError, match="DOCUMENT_PATH_OUTSIDE_ROOT"):
        await loader.load(source("../secret.txt"))
