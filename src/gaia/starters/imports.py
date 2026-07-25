"""Loading for explicitly declared custom starter references."""

from __future__ import annotations

import importlib

from gaia.config import ImportedStarterRef
from gaia.starters.core import GaiaStarter


def resolve_imported_starter(reference: ImportedStarterRef) -> GaiaStarter:
    module_name, attribute = reference.import_.split(":", 1)
    try:
        candidate = getattr(importlib.import_module(module_name), attribute)
    except (AttributeError, ImportError, ModuleNotFoundError) as error:
        raise ValueError(f"CONFIG_STARTER_IMPORT_ERROR:{reference.import_}") from error
    if not isinstance(candidate, GaiaStarter):
        raise ValueError(f"CONFIG_STARTER_IMPORT_ERROR:{reference.import_}")
    return candidate
