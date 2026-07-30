"""Constraint-layer exceptions."""


class ConstraintError(ValueError):
    """Base class for constraint failures."""


class ConstraintValidationError(ConstraintError):
    """Raised when a constraint declaration is structurally invalid."""
