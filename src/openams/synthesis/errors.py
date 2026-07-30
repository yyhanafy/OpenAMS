"""Errors raised by explicit circuit-region synthesis."""


class SynthesisError(Exception):
    """Base error for synthesis-region construction."""


class InvalidRegionError(SynthesisError):
    """Raised when a region or row is structurally invalid."""


class MissingFieldError(SynthesisError, KeyError):
    """Raised when a requested namespaced field is absent."""


class CombinationBudgetExceededError(SynthesisError):
    """Raised before an intersection would exceed its configured budget."""
