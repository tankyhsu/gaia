"""Compatibility import for the single durable Gaia Runtime implementation."""

from gaia.runtime.persistent_engine import PersistentRuntimeEngine

RuntimeEngine = PersistentRuntimeEngine

__all__ = ["PersistentRuntimeEngine", "RuntimeEngine"]
