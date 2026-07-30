import pytest

from openams.constraints import (
    BinaryExpression,
    Constant,
    ConstraintValidationError,
    Symbol,
    UnaryExpression,
    as_expression,
    symbols_in_expression,
)


def test_expression_normalization_and_symbols() -> None:
    expression = BinaryExpression(
        "*",
        BinaryExpression("+", "gm1", 2.0),
        UnaryExpression("-", Symbol("cc")),
    )

    assert isinstance(expression.left.right, Constant)
    assert symbols_in_expression(expression) == frozenset({"gm1", "cc"})
    assert as_expression("vout") == Symbol("vout")
    assert as_expression(3) == Constant(3.0)


def test_invalid_expression_operations_are_rejected() -> None:
    with pytest.raises(ConstraintValidationError, match="operator"):
        UnaryExpression("~", "x")
    with pytest.raises(ConstraintValidationError, match="operator"):
        BinaryExpression("%", "x", 2)
    with pytest.raises(ConstraintValidationError, match="zero"):
        BinaryExpression("/", "x", 0)
    with pytest.raises(TypeError, match="boolean"):
        as_expression(True)
