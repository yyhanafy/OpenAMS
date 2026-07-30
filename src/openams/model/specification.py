"""Canonical design specifications."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._immutable import require_finite_number, require_nonempty


class ComparisonRelation(StrEnum):
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class SpecificationSeverity(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    OBJECTIVE = "objective"
    INFORMATIONAL = "informational"


@dataclass(frozen=True, slots=True)
class Specification:
    name: str
    variable: str
    relation: ComparisonRelation
    target: float
    unit: str
    severity: SpecificationSeverity = SpecificationSeverity.REQUIRED

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        object.__setattr__(self, "variable", require_nonempty(self.variable, "variable"))
        object.__setattr__(self, "unit", require_nonempty(self.unit, "unit"))
        if not isinstance(self.relation, ComparisonRelation):
            raise TypeError("relation must be a ComparisonRelation")
        if not isinstance(self.severity, SpecificationSeverity):
            raise TypeError("severity must be a SpecificationSeverity")
        object.__setattr__(self, "target", require_finite_number(self.target, "target"))
