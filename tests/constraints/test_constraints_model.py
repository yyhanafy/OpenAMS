from types import MappingProxyType

import pytest

from openams.constraints import (
    BinaryExpression,
    BoundConstraint,
    ConstraintSet,
    ConstraintValidationError,
    RatioConstraint,
    RelationConstraint,
    Symbol,
)


def test_represent_common_openams_constraints() -> None:
    symmetry = RelationConstraint(
        identifier="m1_m2_symmetry",
        left=Symbol("w_m1"),
        operator="==",
        right=Symbol("w_m2"),
    )
    ratio = RatioConstraint(
        identifier="stage_ratio",
        numerator="w_m6",
        denominator="w_m4",
        ratio=2.0,
    )
    output_window = BoundConstraint(
        identifier="vout_window",
        symbol="vout",
        lower=0.5,
        upper=2.0,
    )
    equations = ConstraintSet(
        name="two_stage",
        constraints=(symmetry, ratio, output_window),
        provenance={"source": "design_rules"},
    )

    assert equations.constraints == (symmetry, ratio, output_window)
    assert isinstance(equations.provenance, MappingProxyType)
    assert equations.provenance["source"] == "design_rules"


def test_bounds_are_structurally_validated() -> None:
    with pytest.raises(ConstraintValidationError, match="requires"):
        BoundConstraint(identifier="empty", symbol="x")
    with pytest.raises(ConstraintValidationError, match="exceeds"):
        BoundConstraint(identifier="reverse", symbol="x", lower=2, upper=1)
    with pytest.raises(ConstraintValidationError, match="inclusive"):
        BoundConstraint(
            identifier="open_point",
            symbol="x",
            lower=1,
            upper=1,
            lower_inclusive=False,
        )


def test_constraint_identifiers_are_case_insensitively_unique() -> None:
    first = RelationConstraint(
        identifier="Symmetry", left="w1", operator="==", right="w2"
    )
    second = RelationConstraint(
        identifier="symmetry", left="w3", operator="==", right="w4"
    )
    with pytest.raises(ConstraintValidationError, match="duplicate"):
        ConstraintSet(name="bad", constraints=(first, second))


def test_declarations_are_immutable() -> None:
    item = RelationConstraint(
        identifier="eq", left="a", operator="==", right="b"
    )
    with pytest.raises(Exception):
        item.identifier = "changed"
