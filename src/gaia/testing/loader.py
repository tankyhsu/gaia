"""Load versioned test datasets from repository-owned JSON or YAML files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from gaia.testing.models import TestDataset


def load_dataset(path: Path) -> TestDataset:
    """Load and validate a dataset without imposing application-specific semantics."""

    suffix = path.suffix.lower()
    raw_text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        payload: Any = json.loads(raw_text)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_text)
    else:
        raise ValueError("dataset file must use .json, .yaml, or .yml")

    if not isinstance(payload, dict):
        raise ValueError("dataset file must contain a mapping")
    if set(payload) == {"dataset"}:
        payload = payload["dataset"]
    if not isinstance(payload, dict):
        raise ValueError("dataset must be a mapping")
    return TestDataset.model_validate(payload)
