"""Errors raised while preparing backend-neutral simulation work."""


class SimulationError(Exception):
    """Base class for simulation-layer failures."""


class InvalidExecutionPlanError(SimulationError):
    """Raised when a plan cannot legally enter direct simulation."""


class InvalidSimulationManifestError(SimulationError):
    """Raised when a manifest is incomplete or internally inconsistent."""
