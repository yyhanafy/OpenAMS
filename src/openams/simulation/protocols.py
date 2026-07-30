"""Protocols implemented by concrete simulator adapters."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .model import SimulationRunRequest


@runtime_checkable
class SimulationRunner(Protocol):
    """Backend adapter boundary; implementations may invoke ngspice or others."""

    def run(self, request: SimulationRunRequest) -> Any:
        """Execute the request and return a backend-specific raw result."""
        ...
