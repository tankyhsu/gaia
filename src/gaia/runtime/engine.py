"""Public execution Runtime protocol.

This module no longer aliases ``RuntimeEngine`` to Gaia's legacy SQL executor.
Applications receive the configured implementation from ``RuntimeAssembler``;
code that needs the boundary imports this protocol.
"""

from gaia.runtime.contracts import RuntimeEngine

__all__ = ["RuntimeEngine"]
