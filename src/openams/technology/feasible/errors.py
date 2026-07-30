"""Errors raised by generic feasible-region construction."""

class FeasibleRegionError(Exception):
    """Base error for feasible-region construction."""


class InvalidConstraintError(FeasibleRegionError, ValueError):
    """Raised when a constraint definition is invalid."""


class MissingFieldError(FeasibleRegionError, KeyError):
    """Raised when a required row field is absent."""
