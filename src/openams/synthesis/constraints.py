"""Generic constraints evaluated over namespaced circuit rows."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Protocol

from .errors import MissingFieldError, SynthesisError
from .model import ConstraintDecision


class CircuitConstraint(Protocol):
    @property
    def name(self) -> str: ...

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision: ...


def _numeric(row: Mapping[str, Any], field: str) -> float:
    if field not in row:
        raise MissingFieldError(field)
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SynthesisError(f"field {field!r} is not numeric")
    number = float(value)
    if not isfinite(number):
        raise SynthesisError(f"field {field!r} is not finite")
    return number


@dataclass(frozen=True)
class FieldRelationConstraint:
    """Enforce left ~= scale*right + offset."""

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
            raise SynthesisError("relation parameters must be finite")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise SynthesisError("relation tolerances must be non-negative")

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
            "" if accepted else f"{self.left}={left} differs from expected {expected} by {error} > {tolerance}",
            {"left": left, "right": right, "expected": expected, "error": error, "tolerance": tolerance},
        )


@dataclass(frozen=True)
class SumConstraint:
    """Enforce target ~= sum(coeff_i * field_i) + offset; useful for KCL."""

    target: str
    terms: tuple[tuple[float, str], ...]
    offset: float = 0.0
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.terms:
            raise SynthesisError("sum constraint requires at least one term")
        scalars = [self.offset, self.absolute_tolerance, self.relative_tolerance]
        scalars.extend(coefficient for coefficient, _ in self.terms)
        if not all(isfinite(value) for value in scalars):
            raise SynthesisError("sum constraint parameters must be finite")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise SynthesisError("sum tolerances must be non-negative")

    @property
    def name(self) -> str:
        return self.label or f"{self.target}_sum_relation"

    def evaluate(self, row: Mapping[str, Any]) -> ConstraintDecision:
        actual = _numeric(row, self.target)
        expected = self.offset + sum(coefficient * _numeric(row, field) for coefficient, field in self.terms)
        tolerance = self.absolute_tolerance + self.relative_tolerance * abs(expected)
        error = abs(actual - expected)
        accepted = error <= tolerance
        return ConstraintDecision(
            accepted,
            "" if accepted else f"{self.target}={actual} differs from sum {expected} by {error} > {tolerance}",
            {"actual": actual, "expected": expected, "error": error, "tolerance": tolerance},
        )


@dataclass(frozen=True)
class AllowedValuesConstraint:
    field: str
    allowed: frozenset[Any]
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.allowed:
            raise SynthesisError("allowed set must not be empty")

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
