"""Dependency inspection for immutable constraints."""

from __future__ import annotations

from .expressions import symbols_in_expression
from .model import (
    BoundConstraint,
    Constraint,
    ConstraintSet,
    RatioConstraint,
    RelationConstraint,
)


def symbols_in_constraint(constraint: Constraint) -> frozenset[str]:
    """Return every symbol referenced by one constraint."""

    if isinstance(constraint, BoundConstraint):
        return frozenset({constraint.symbol})
    if isinstance(constraint, RatioConstraint):
        return (
            symbols_in_expression(constraint.numerator)
            | symbols_in_expression(constraint.denominator)
        )
    if isinstance(constraint, RelationConstraint):
        return (
            symbols_in_expression(constraint.left)
            | symbols_in_expression(constraint.right)
        )
    raise TypeError(f"unsupported constraint {type(constraint).__name__}")


def symbols_in_constraint_set(constraints: ConstraintSet) -> frozenset[str]:
    """Return every symbol referenced by a constraint set."""

    result: frozenset[str] = frozenset()
    for constraint in constraints.constraints:
        result |= symbols_in_constraint(constraint)
    return result
