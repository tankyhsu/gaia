from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from gaia import fingerprint


def test_same_content_yields_same_digest(tmp_path: Path) -> None:
    path = tmp_path / "content.txt"
    path.write_text("alpha", encoding="utf-8")

    assert fingerprint(path) == fingerprint(path)
    assert fingerprint(path) == fingerprint(str(path))


def test_different_content_yields_different_digest(tmp_path: Path) -> None:
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("alpha", encoding="utf-8")
    path_b.write_text("beta", encoding="utf-8")

    assert fingerprint(path_a) != fingerprint(path_b)


def test_multiple_sources_are_order_sensitive(tmp_path: Path) -> None:
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("alpha", encoding="utf-8")
    path_b.write_text("beta", encoding="utf-8")

    assert fingerprint(path_a, path_b) != fingerprint(path_b, path_a)
    assert fingerprint(path_a, path_b) == fingerprint(path_a, path_b)


def test_mapping_source_uses_canonical_json() -> None:
    # Key insertion order must not matter: canonical JSON sorts keys.
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_sequence_source_is_order_sensitive() -> None:
    assert fingerprint([1, 2, 3]) != fingerprint([3, 2, 1])


def test_module_and_function_sources_use_inspect_getsource() -> None:
    import gaia._authoring.versioning as versioning_module

    assert fingerprint(versioning_module) == fingerprint(versioning_module)
    assert fingerprint(fingerprint) == fingerprint(fingerprint)
    assert fingerprint(versioning_module) != fingerprint(fingerprint)


def test_qualified_true_has_prefix_and_qualified_false_has_no_colon() -> None:
    qualified = fingerprint({"k": "v"}, qualified=True)
    bare = fingerprint({"k": "v"}, qualified=False)

    assert qualified.startswith("sha256:")
    assert ":" not in bare
    assert qualified == f"sha256:{bare}"


def test_length_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        fingerprint({"k": "v"}, length=7)
    with pytest.raises(ValueError):
        fingerprint({"k": "v"}, length=65)
    # Boundaries are inclusive.
    assert len(fingerprint({"k": "v"}, length=8, qualified=False)) == 8
    assert len(fingerprint({"k": "v"}, length=64, qualified=False)) == 64


def test_missing_file_raises_value_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.txt"
    with pytest.raises(ValueError, match="does not exist"):
        fingerprint(missing)


def test_unsourceable_object_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported fingerprint source type"):
        fingerprint(42)


def test_object_without_retrievable_source_raises_value_error() -> None:
    # A dynamically created function has no backing source file, so
    # inspect.getsource must fail -- and fingerprint must not silently
    # fall back to hashing a repr() of it.
    dynamic = eval("lambda: None")  # noqa: S307 - deliberately source-less
    with pytest.raises(ValueError, match="cannot read source"):
        fingerprint(dynamic)


def test_no_sources_raises_value_error() -> None:
    with pytest.raises(ValueError):
        fingerprint()


def test_deterministic_across_fresh_interpreters(tmp_path: Path) -> None:
    """`fingerprint` must never depend on PYTHONHASHSEED-randomized hash()/id().

    Python randomizes `hash(str)` per process by default, so if the
    implementation ever used `hash()`/`id()` as a shortcut, this test would
    catch it: the same file fingerprinted in two independent interpreters
    would disagree.
    """
    content_path = tmp_path / "shared.txt"
    content_path.write_text("deterministic-content", encoding="utf-8")

    in_process = fingerprint(content_path)

    script = textwrap.dedent(
        f"""
        from gaia import fingerprint
        print(fingerprint({str(content_path)!r}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    out_of_process = completed.stdout.strip()

    assert out_of_process == in_process
