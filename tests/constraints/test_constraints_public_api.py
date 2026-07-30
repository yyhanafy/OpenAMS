def test_constraints_public_api() -> None:
    import openams.constraints as constraints

    assert set(constraints.__all__) == {
        "BinaryExpression",
        "BoundConstraint",
        "Constant",
        "Constraint",
        "ConstraintError",
        "ConstraintSet",
        "ConstraintValidationError",
        "Expression",
        "RatioConstraint",
        "RelationConstraint",
        "Symbol",
        "UnaryExpression",
        "as_expression",
        "symbols_in_constraint",
        "symbols_in_constraint_set",
        "symbols_in_expression",
        "validate_constraint_set",
    }
