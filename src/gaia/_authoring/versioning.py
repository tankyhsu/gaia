"""Deterministic content fingerprints for trustworthy version evidence.

`@scenario(rules_version="1.0.0", ...)` and friends take hand-typed version
strings. Nothing forces the string to change when the content it names
changes: edit `rules.py`, forget to bump the literal, and the `VersionBundle`
recorded in every Run's audit evidence keeps reporting the *old* version
against the *new* behaviour. For a framework whose value proposition is
auditable controlled execution, that drift is worse than having no version
at all -- an evidence trail that can silently lie is trusted precisely
because it looks authoritative.

`fingerprint()` replaces the hand-typed literal with a digest computed from
the content itself, so the version *is* a function of the content:

    rules_version = fingerprint(rules)                    # 'sha256:3f1a9c0d2e4b'
    digest        = fingerprint(payload, qualified=False)  # '3f1a9c0d2e4b'

Change the rules module and `rules_version` changes on the next import --
there is no literal to forget.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import FunctionType, MethodType, ModuleType
from typing import cast

_MIN_LENGTH = 8
_MAX_LENGTH = 64


def fingerprint(*sources: object, length: int = 12, qualified: bool = True) -> str:
    """Return a deterministic content version for one or more sources.

    Each source is hashed independently and then, for more than one source,
    the resulting digests are concatenated (in argument order) and hashed
    again -- so the result is sensitive to both content and order, and a
    single source's fingerprint is simply the digest of its own content.

    Accepted source types:
      - `pathlib.Path`, or a `str` that names an existing file: the file's
        bytes are hashed.
      - a module, class, function, or method: `inspect.getsource` is hashed.
      - a `Mapping` or `Sequence` (other than `str`/`bytes`): the value is
        serialized to canonical JSON (`sort_keys=True`, compact separators)
        and the JSON text is hashed.

    Args:
        length: number of hex characters to keep from the final digest.
            Must satisfy `8 <= length <= 64`.
        qualified: when `True` (the default), the result is prefixed with
            `"sha256:"` -- a human-facing, self-describing version string.
            When `False`, the bare hex digest is returned with no prefix and
            no colon, so it can be embedded in strings (such as a PEP 440
            local version segment) that forbid `:`.

    Raises:
        ValueError: `length` is out of range, no sources were given, a `str`
            or `Path` source does not name an existing file, `inspect.getsource`
            fails on a module/class/function/method, a `Mapping`/`Sequence`
            source is not JSON-serializable, or a source is none of the
            accepted types. This function never falls back to hashing a
            `repr()` or other non-authoritative stand-in: a fingerprint that
            silently degrades is worse than no fingerprint, because it still
            looks authoritative.

    Determinism:
        The digest depends only on the byte content produced above -- never
        on `hash()`, `id()`, iteration order of unordered containers, or any
        other per-process or per-run salt -- so the same input yields the
        same fingerprint across processes and interpreter restarts.
    """
    if not (_MIN_LENGTH <= length <= _MAX_LENGTH):
        raise ValueError(
            f"length must satisfy {_MIN_LENGTH} <= length <= {_MAX_LENGTH}, got {length}"
        )
    if not sources:
        raise ValueError("fingerprint requires at least one source")

    digests = [_digest_source(source) for source in sources]
    combined = digests[0] if len(digests) == 1 else _sha256_hex("".join(digests).encode("ascii"))
    truncated = combined[:length]
    return f"sha256:{truncated}" if qualified else truncated


def _digest_source(source: object) -> str:
    return _sha256_hex(_content_bytes(source))


def _content_bytes(source: object) -> bytes:
    if isinstance(source, Path | str):
        path = Path(source)
        if not path.is_file():
            raise ValueError(f"fingerprint source file does not exist: {source!r}")
        return path.read_bytes()
    is_sourceable = (
        inspect.ismodule(source)
        or inspect.isclass(source)
        or inspect.isfunction(source)
        or inspect.ismethod(source)
    )
    if is_sourceable:
        try:
            text = inspect.getsource(cast(ModuleType | type | MethodType | FunctionType, source))
        except (OSError, TypeError) as error:
            raise ValueError(f"cannot read source for fingerprint: {source!r}") from error
        return text.encode("utf-8")
    if isinstance(source, Mapping) or (
        isinstance(source, Sequence) and not isinstance(source, str | bytes)
    ):
        try:
            canonical = json.dumps(
                source, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except TypeError as error:
            raise ValueError(f"fingerprint source is not JSON-serializable: {error}") from error
        return canonical.encode("utf-8")
    raise ValueError(f"unsupported fingerprint source type: {type(source).__name__}")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
