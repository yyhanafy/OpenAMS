"""Explicit circuit-region synthesis by deterministic region intersection."""

from .constraints import (
    AllowedValuesConstraint,
    CircuitConstraint,
    FieldRelationConstraint,
    SumConstraint,
)
from .errors import (
    CombinationBudgetExceededError,
    InvalidRegionError,
    MissingFieldError,
    SynthesisError,
)
from .intersection import IntersectionPolicy, RegionIntersection
from .model import (
    CircuitRegion,
    CircuitRow,
    ConstraintDecision,
    RegionInput,
    RejectedCombination,
)

__all__ = [
    "AllowedValuesConstraint",
    "CircuitConstraint",
    "CircuitRegion",
    "CircuitRow",
    "CombinationBudgetExceededError",
    "ConstraintDecision",
    "FieldRelationConstraint",
    "IntersectionPolicy",
    "InvalidRegionError",
    "MissingFieldError",
    "RegionInput",
    "RegionIntersection",
    "RejectedCombination",
    "SumConstraint",
    "SynthesisError",
]
