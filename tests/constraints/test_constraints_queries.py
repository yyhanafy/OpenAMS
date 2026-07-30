from openams.constraints import (
    BinaryExpression,
    BoundConstraint,
    ConstraintSet,
    RatioConstraint,
    RelationConstraint,
    symbols_in_constraint,
    symbols_in_constraint_set,
)


def test_constraint_dependency_queries() -> None:
    equation = RelationConstraint(
        identifier="gm",
        left="gm1",
        operator="==",
        right=BinaryExpression("*", 2.0, "pi_gb_cc"),
    )
    ratio = RatioConstraint(
        identifier="ratio",
        numerator="w6",
        denominator="w4",
        ratio=2.0,
    )
    bound = BoundConstraint(
        identifier="vout",
        symbol="vout",
        lower=0.5,
        upper=2.0,
    )
    constraint_set = ConstraintSet(
        name="design",
        constraints=(equation, ratio, bound),
    )

    assert symbols_in_constraint(equation) == frozenset({"gm1", "pi_gb_cc"})
    assert symbols_in_constraint_set(constraint_set) == frozenset(
        {"gm1", "pi_gb_cc", "w6", "w4", "vout"}
    )
