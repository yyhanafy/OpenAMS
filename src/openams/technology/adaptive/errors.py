"""Errors raised by adaptive technology-table generation."""

class AdaptiveTableError(Exception):
    """Base class for adaptive table generation failures."""

class InvalidSamplingDomainError(AdaptiveTableError):
    """The requested sampling domain is invalid."""

class PointBudgetExceededError(AdaptiveTableError):
    """The requested grid exceeds its configured point budget."""

class ModelEvaluationError(AdaptiveTableError):
    """The continuous model could not evaluate a requested point."""
