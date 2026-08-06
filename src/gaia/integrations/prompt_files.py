"""Versioned prompt artifacts stored as ordinary YAML files."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml

from gaia.spi.prompt import PromptArtifact, PromptRef


class PromptNotFoundError(LookupError):
    """Raised when an exact prompt artifact does not exist."""


class FilePromptProvider:
    """Read ``<root>/<prompt_id>/<version>.yaml`` on explicit resolution."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    async def resolve(self, ref: PromptRef) -> PromptArtifact:
        if ref.version is None:
            raise ValueError("file prompt provider requires an exact version")
        return await asyncio.to_thread(self._resolve, ref)

    async def list_artifacts(self) -> tuple[PromptArtifact, ...]:
        return await asyncio.to_thread(self._list_artifacts)

    def _list_artifacts(self) -> tuple[PromptArtifact, ...]:
        if not self._root.is_dir():
            return ()
        return tuple(
            self._resolve(
                PromptRef(
                    prompt_id=path.parent.name,
                    version=path.stem,
                )
            )
            for path in sorted(self._root.glob("*/*.yaml"))
        )

    def _resolve(self, ref: PromptRef) -> PromptArtifact:
        assert ref.version is not None
        path = (self._root / ref.prompt_id / f"{ref.version}.yaml").resolve()
        if not path.is_relative_to(self._root):
            raise PromptNotFoundError(f"PROMPT_OUTSIDE_ROOT:{ref.prompt_id}:{ref.version}")
        if not path.is_file():
            raise PromptNotFoundError(f"PROMPT_NOT_FOUND:{ref.prompt_id}:{ref.version}")
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"PROMPT_ARTIFACT_INVALID:{path}")
        artifact = PromptArtifact.model_validate(raw)
        if artifact.ref != ref:
            raise ValueError(f"PROMPT_REF_MISMATCH:{path}")
        return artifact
