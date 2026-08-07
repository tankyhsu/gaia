"""Keep Gaia's public brand mark consistent across every first-party surface."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS_MARK = ROOT / "developer-docs" / "assets" / "gaia-mark.svg"
WEB_MARK = ROOT / "apps" / "web" / "public" / "gaia-mark.svg"


def test_vector_mark_is_accessible_and_shared_without_drift() -> None:
    mark = DOCS_MARK.read_text()

    assert WEB_MARK.read_bytes() == DOCS_MARK.read_bytes()
    assert 'viewBox="0 0 256 256"' in mark
    assert "<title" in mark
    assert "<desc" in mark
    assert "#178F73" in mark
    assert "#E5A13A" in mark
    assert "<text" not in mark


def test_repository_docs_and_console_use_the_vector_mark() -> None:
    readme = (ROOT / "README.md").read_text()
    mkdocs = yaml.safe_load((ROOT / "mkdocs.yml").read_text())
    console = (ROOT / "apps" / "web" / "src" / "Console.tsx").read_text()
    web_index = (ROOT / "apps" / "web" / "index.html").read_text()

    assert 'src="developer-docs/assets/gaia-mark.svg"' in readme
    assert mkdocs["theme"]["logo"] == "assets/gaia-mark.svg"
    assert mkdocs["theme"]["favicon"] == "assets/gaia-mark.svg"
    assert 'src="/gaia-mark.svg" alt="Gaia 标志"' in console
    assert 'rel="icon" type="image/svg+xml" href="/gaia-mark.svg"' in web_index
