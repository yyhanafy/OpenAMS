"""Planning-layer exceptions."""


class PlanningError(ValueError):
    """Base class for planning failures."""


class PlanningValidationError(PlanningError):
    """Raised when planning declarations are inconsistent."""
