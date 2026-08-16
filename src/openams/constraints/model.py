"""Immutable constraint declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from ._immutable import freeze_mapping, require_finite, require_name
from .errors import ConstraintValidationError
from .expressions import Expression, ExpressionLike, as_expression

_RELATION_OPERATORS = frozenset({"==", "!=", "<", "<=", ">", ">="})


@dataclass(frozen=True, slots=True, kw_only=True)
class RelationConstraint:
    identifier: str
    left: Expression
    operator: str
    right: Expression
    description: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier", require_name(self.identifier, "constraint identifier")
        )
        if self.operator not in _RELATION_OPERATORS:
            raise ConstraintValidationError(
                f"unsupported relation operator {self.operator!r}"
            )
        object.__setattr__(self, "left", as_expression(self.left))
        object.__setattr__(self, "right", as_expression(self.right))
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundConstraint:
    identifier: str
    symbol: str
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    description: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier", require_name(self.identifier, "constraint identifier")
        )
        object.__setattr__(self, "symbol", require_name(self.symbol, "bound symbol"))

        lower = None if self.lower is None else require_finite(self.lower, "lower bound")
        upper = None if self.upper is None else require_finite(self.upper, "upper bound")
        if lower is None and upper is None:
            raise ConstraintValidationError(
                "bound constraint requires a lower or upper bound"
            )
        if lower is not None and upper is not None:
            if lower > upper:
                raise ConstraintValidationError("lower bound exceeds upper bound")
            if lower == upper and not (
                self.lower_inclusive and self.upper_inclusive
            ):
                raise ConstraintValidationError(
                    "equal bounds must both be inclusive"
                )

        if not isinstance(self.lower_inclusive, bool):
            raise TypeError("lower_inclusive must be boolean")
        if not isinstance(self.upper_inclusive, bool):
            raise TypeError("upper_inclusive must be boolean")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))


@dataclass(frozen=True, slots=True, kw_only=True)
class RatioConstraint:
    identifier: str
    numerator: Expression
    denominator: Expression
    ratio: float
    description: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier", require_name(self.identifier, "constraint identifier")
        )
        object.__setattr__(self, "numerator", as_expression(self.numerator))
        object.__setattr__(self, "denominator", as_expression(self.denominator))
        object.__setattr__(self, "ratio", require_finite(self.ratio, "ratio"))
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))


Constraint: TypeAlias = RelationConstraint | BoundConstraint | RatioConstraint


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintSet:
    name: str
    constraints: tuple[Constraint, ...]
    description: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "constraint set name"))
        constraints = tuple(self.constraints)
        for item in constraints:
            if not isinstance(
                item, (RelationConstraint, BoundConstraint, RatioConstraint)
            ):
                raise TypeError(
                    "constraints must contain constraint model instances"
                )

        identifiers: set[str] = set()
        for item in constraints:
            key = item.identifier.lower()
            if key in identifiers:
                raise ConstraintValidationError(
                    f"duplicate constraint identifier {item.identifier!r}"
                )
            identifiers.add(key)

        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))
