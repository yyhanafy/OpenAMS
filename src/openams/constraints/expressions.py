"""Immutable scalar expression tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ._immutable import require_finite, require_name
from .errors import ConstraintValidationError

_UNARY_OPERATORS = frozenset({"+", "-"})
_BINARY_OPERATORS = frozenset({"+", "-", "*", "/", "**"})


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "symbol name"))


@dataclass(frozen=True, slots=True)
class Constant:
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", require_finite(self.value, "constant value"))


@dataclass(frozen=True, slots=True)
class UnaryExpression:
    operator: str
    operand: "Expression"

    def __post_init__(self) -> None:
        if self.operator not in _UNARY_OPERATORS:
            raise ConstraintValidationError(
                f"unsupported unary operator {self.operator!r}"
            )
        object.__setattr__(self, "operand", as_expression(self.operand))


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    operator: str
    left: "Expression"
    right: "Expression"

    def __post_init__(self) -> None:
        if self.operator not in _BINARY_OPERATORS:
            raise ConstraintValidationError(
                f"unsupported binary operator {self.operator!r}"
            )
        left = as_expression(self.left)
        right = as_expression(self.right)
        if (
            self.operator == "/"
            and isinstance(right, Constant)
            and right.value == 0.0
        ):
            raise ConstraintValidationError("division by literal zero")
        object.__setattr__(self, "left", left)
        object.__setattr__(self, "right", right)


Expression: TypeAlias = Symbol | Constant | UnaryExpression | BinaryExpression
ExpressionLike: TypeAlias = Expression | str | int | float


def as_expression(value: ExpressionLike) -> Expression:
    """Normalize a stable scalar value into an expression node."""

    if isinstance(value, (Symbol, Constant, UnaryExpression, BinaryExpression)):
        return value
    if isinstance(value, str):
        return Symbol(value)
    if isinstance(value, bool):
        raise TypeError("boolean is not a scalar expression")
    if isinstance(value, (int, float)):
        return Constant(value)
    raise TypeError(f"unsupported expression value {type(value).__name__}")


def symbols_in_expression(expression: ExpressionLike) -> frozenset[str]:
    """Return all symbol names referenced by an expression."""

    current = as_expression(expression)
    if isinstance(current, Symbol):
        return frozenset({current.name})
    if isinstance(current, Constant):
        return frozenset()
    if isinstance(current, UnaryExpression):
        return symbols_in_expression(current.operand)
    return (
        symbols_in_expression(current.left)
        | symbols_in_expression(current.right)
    )
