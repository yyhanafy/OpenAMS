"""Generic construction of explicit feasible technology regions."""

from .builder import FeasibleRegionBuilder, FeasibleRegionPolicy
from .constraints import (
    AllowedValuesConstraint,
    BooleanConstraint,
    FieldRelationConstraint,
    RangeConstraint,
    RowConstraint,
)
from .errors import FeasibleRegionError, InvalidConstraintError, MissingFieldError
from .model import ConstraintDecision, FeasibleRegion, RejectedPoint

__all__ = [
    "AllowedValuesConstraint",
    "BooleanConstraint",
    "ConstraintDecision",
    "FeasibleRegion",
    "FeasibleRegionBuilder",
    "FeasibleRegionError",
    "FeasibleRegionPolicy",
    "FieldRelationConstraint",
    "InvalidConstraintError",
    "MissingFieldError",
    "RangeConstraint",
    "RejectedPoint",
    "RowConstraint",
]
