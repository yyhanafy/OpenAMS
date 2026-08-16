"""Safe expression evaluation for generic DC propagation metadata."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from openams.synthesis.dc_propagation_state import Interval


class ExpressionError(ValueError):
    """Raised for unsupported or unresolved expressions."""


_ALLOWED_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
}


def _resolve_attribute(root: Any, attributes: list[str]) -> Any:
    value = root
    for attribute in attributes:
        if isinstance(value, Interval):
            if attribute == "minimum":
                value = value.minimum
            elif attribute == "maximum":
                value = value.maximum
            else:
                raise ExpressionError(
                    f"interval has no attribute {attribute!r}"
                )
        elif isinstance(value, Mapping):
            if attribute not in value:
                raise ExpressionError(
                    f"mapping has no field {attribute!r}"
                )
            value = value[attribute]
        else:
            raise ExpressionError(
                f"cannot access {attribute!r} on {type(value).__name__}"
            )
    return value


def evaluate_expression(
    expression: str,
    *,
    scalars: Mapping[str, float],
    intervals: Mapping[str, Interval],
    candidate: Mapping[str, Any] | None = None,
    left: Mapping[str, Any] | None = None,
    right: Mapping[str, Any] | None = None,
) -> Any:
    """Evaluate one restricted metadata expression."""

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(
            f"invalid expression syntax: {expression!r}"
        ) from exc

    # Scalars and intervals may intentionally share a name.
    #
    # Bare references such as ``vdd_v`` resolve to the scalar value.
    # Endpoint references such as ``vdd_v.minimum`` resolve through
    # the interval namespace.
    roots: dict[str, Any] = {
        "candidate": candidate,
        "left": left,
        "right": right,
        "True": True,
        "False": False,
    }

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, bool)):
                return node.value
            raise ExpressionError(
                f"unsupported constant {node.value!r}"
            )

        if isinstance(node, ast.Name):
            # Bare variable names prefer exact scalar values.
            if node.id in scalars:
                return scalars[node.id]
            if node.id in intervals:
                return intervals[node.id]
            if node.id in roots and roots[node.id] is not None:
                return roots[node.id]
            raise ExpressionError(f"unknown name {node.id!r}")

        if isinstance(node, ast.Attribute):
            attributes: list[str] = []
            current: ast.AST = node
            while isinstance(current, ast.Attribute):
                attributes.append(current.attr)
                current = current.value
            if not isinstance(current, ast.Name):
                raise ExpressionError(
                    "attribute root must be a simple name"
                )
            root_name = current.id

            # Endpoint references prefer the interval namespace, while
            # candidate/left/right fields use the contextual roots.
            if root_name in intervals:
                root_value = intervals[root_name]
            elif root_name in roots and roots[root_name] is not None:
                root_value = roots[root_name]
            elif root_name in scalars:
                root_value = scalars[root_name]
            else:
                raise ExpressionError(
                    f"unknown attribute root {root_name!r}"
                )

            return _resolve_attribute(
                root_value,
                list(reversed(attributes)),
            )

        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.Not):
                return not value
            raise ExpressionError(
                f"unsupported unary operator {type(node.op).__name__}"
            )

        if isinstance(node, ast.BinOp):
            left_value = visit(node.left)
            right_value = visit(node.right)

            if isinstance(node.op, ast.Add):
                return left_value + right_value
            if isinstance(node.op, ast.Sub):
                return left_value - right_value
            if isinstance(node.op, ast.Mult):
                return left_value * right_value
            if isinstance(node.op, ast.Div):
                return left_value / right_value

            raise ExpressionError(
                f"unsupported binary operator {type(node.op).__name__}"
            )

        if isinstance(node, ast.BoolOp):
            values = [bool(visit(item)) for item in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ExpressionError(
                f"unsupported boolean operator {type(node.op).__name__}"
            )

        if isinstance(node, ast.Compare):
            current = visit(node.left)
            for operator, comparator in zip(
                node.ops,
                node.comparators,
            ):
                other = visit(comparator)

                if isinstance(operator, ast.Eq):
                    passed = current == other
                elif isinstance(operator, ast.NotEq):
                    passed = current != other
                elif isinstance(operator, ast.Lt):
                    passed = current < other
                elif isinstance(operator, ast.LtE):
                    passed = current <= other
                elif isinstance(operator, ast.Gt):
                    passed = current > other
                elif isinstance(operator, ast.GtE):
                    passed = current >= other
                else:
                    raise ExpressionError(
                        f"unsupported comparison {type(operator).__name__}"
                    )

                if not passed:
                    return False
                current = other

            return True

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExpressionError(
                    "only simple function calls are allowed"
                )
            if node.func.id not in _ALLOWED_FUNCTIONS:
                raise ExpressionError(
                    f"unsupported function {node.func.id!r}"
                )
            if node.keywords:
                raise ExpressionError(
                    "keyword arguments are not supported"
                )
            return _ALLOWED_FUNCTIONS[node.func.id](
                *(visit(argument) for argument in node.args)
            )

        raise ExpressionError(
            f"unsupported expression node {type(node).__name__}"
        )

    return visit(tree)
