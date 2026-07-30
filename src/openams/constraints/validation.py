"""Explicit structural validation entry points."""

from __future__ import annotations

from .errors import ConstraintValidationError
from .model import ConstraintSet


def validate_constraint_set(
    constraints: ConstraintSet,
    *,
    allow_empty: bool = True,
) -> ConstraintSet:
    """Validate and return a constraint set.

    Dataclass construction already validates individual declarations. This
    function provides a stable orchestration boundary for callers and for later
    cross-record checks.
    """

    if not isinstance(constraints, ConstraintSet):
        raise TypeError("constraints must be a ConstraintSet")
    if not isinstance(allow_empty, bool):
        raise TypeError("allow_empty must be boolean")
    if not allow_empty and not constraints.constraints:
        raise ConstraintValidationError("constraint set must not be empty")
    return constraints
