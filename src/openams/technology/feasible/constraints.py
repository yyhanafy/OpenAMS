"""Generic row constraints for model-generated technology tables."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Protocol

from .errors import InvalidConstraintError, MissingFieldError
from .model import ConstraintDecision


class RowConstraint(Protocol):
    """Bidirection-free test over one explicit correlated operating point."""

    @property
    def name(self) -> str: ...

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision: ...


def _numeric(row: Mapping[str, Any], field: str) -> float:
    if field not in row:
        raise MissingFieldError(field)
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidConstraintError(f"field {field!r} is not numeric")
    number = float(value)
    if not isfinite(number):
        raise InvalidConstraintError(f"field {field!r} is not finite")
    return number


@dataclass(frozen=True)
class RangeConstraint:
    """Require one numeric row field to lie inside a closed interval."""

    field: str
    minimum: float
    maximum: float
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.field.strip():
            raise InvalidConstraintError("constraint field must be non-empty")
        if not (isfinite(self.minimum) and isfinite(self.maximum)):
            raise InvalidConstraintError("range bounds must be finite")
        if self.minimum > self.maximum:
            raise InvalidConstraintError("range minimum exceeds maximum")

    @property
    def name(self) -> str:
        return self.label or f"{self.field}_range"

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision:
        value = _numeric(row, self.field)
        accepted = self.minimum <= value <= self.maximum
        return ConstraintDecision(
            accepted,
            "" if accepted else f"{self.field}={value} outside [{self.minimum}, {self.maximum}]",
            {"field": self.field, "value": value, "minimum": self.minimum, "maximum": self.maximum},
        )


@dataclass(frozen=True)
class BooleanConstraint:
    """Require one row field to equal a requested Boolean value."""

    field: str
    required: bool = True
    label: str | None = None

    @property
    def name(self) -> str:
        return self.label or f"{self.field}_is_{str(self.required).lower()}"

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision:
        if self.field not in row:
            raise MissingFieldError(self.field)
        actual = row[self.field]
        accepted = actual is self.required
        return ConstraintDecision(
            accepted,
            "" if accepted else f"{self.field} is {actual!r}, required {self.required!r}",
            {"field": self.field, "actual": actual, "required": self.required},
        )


@dataclass(frozen=True)
class AllowedValuesConstraint:
    """Require a row field to belong to an explicit finite value set."""

    field: str
    allowed: frozenset[Any]
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.allowed:
            raise InvalidConstraintError("allowed value set must not be empty")

    @property
    def name(self) -> str:
        return self.label or f"{self.field}_allowed"

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision:
        if self.field not in row:
            raise MissingFieldError(self.field)
        value = row[self.field]
        accepted = value in self.allowed
        return ConstraintDecision(
            accepted,
            "" if accepted else f"{self.field}={value!r} is not allowed",
            {"field": self.field, "value": value, "allowed": tuple(self.allowed)},
        )


@dataclass(frozen=True)
class FieldRelationConstraint:
    """Compare two numeric fields with an optional scale and tolerance.

    It enforces: left ~= scale * right + offset.
    """

    left: str
    right: str
    scale: float = 1.0
    offset: float = 0.0
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    label: str | None = None

    def __post_init__(self) -> None:
        values = (self.scale, self.offset, self.absolute_tolerance, self.relative_tolerance)
        if not all(isfinite(value) for value in values):
            raise InvalidConstraintError("relation parameters must be finite")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise InvalidConstraintError("relation tolerances must be non-negative")

    @property
    def name(self) -> str:
        return self.label or f"{self.left}_relates_to_{self.right}"

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision:
        left = _numeric(row, self.left)
        right = _numeric(row, self.right)
        expected = self.scale * right + self.offset
        tolerance = self.absolute_tolerance + self.relative_tolerance * abs(expected)
        error = abs(left - expected)
        accepted = error <= tolerance
        return ConstraintDecision(
            accepted,
            "" if accepted else f"|{self.left} - ({self.scale}*{self.right}+{self.offset})|={error} > {tolerance}",
            {"left": left, "right": right, "expected": expected, "error": error, "tolerance": tolerance},
        )
