"""Resolve explicit secret references at the application composition boundary."""

from __future__ import annotations

import os
from pathlib import Path

from gaia.config.models import SecretRef


def resolve_secret(value: str | SecretRef, *, environ: dict[str, str] | None = None) -> str:
    if isinstance(value, str):
        return value
    environment = os.environ if environ is None else environ
    if value.env is not None:
        try:
            return environment[value.env]
        except KeyError as error:
            raise ValueError(f"CONFIG_SECRET_UNAVAILABLE:{value.env}") from error
    path = Path(value.file or "")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError("CONFIG_SECRET_UNAVAILABLE:file") from error


def resolve_store_url(
    value: str | SecretRef | None,
    fallback: str | SecretRef,
    *,
    environ: dict[str, str] | None = None,
) -> str:
    return resolve_secret(fallback if value is None else value, environ=environ)
