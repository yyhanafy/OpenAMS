from __future__ import annotations

import pytest

from openams.synthesis import (
    AllowedValuesConstraint,
    CombinationBudgetExceededError,
    FieldRelationConstraint,
    IntersectionPolicy,
    InvalidRegionError,
    RegionInput,
    RegionIntersection,
    SumConstraint,
)


def region(name, rows):
    return RegionInput(name, tuple(rows))


def test_explicit_mirror_intersection_retains_only_matching_rows():
    m3 = region("M3", ({"id": 10.0, "w": 2.0}, {"id": 20.0, "w": 4.0}))
    m4 = region("M4", ({"id": 10.0, "w": 2.0}, {"id": 20.0, "w": 8.0}))
    result = RegionIntersection((
        FieldRelationConstraint("M3.id", "M4.id", label="equal_current"),
        FieldRelationConstraint("M3.w", "M4.w", label="equal_width"),
    )).build((m3, m4))
    assert result.retained_count == 1
    assert result.rows[0].values["M3.id"] == 10.0
    assert result.rows[0].source_indices == {"M3": 0, "M4": 0}


def test_kcl_sum_constraint_joins_three_regions():
    tail = region("M5", ({"id": 20.0}, {"id": 30.0}))
    left = region("M1", ({"id": 10.0}, {"id": 15.0}))
    right = region("M2", ({"id": 10.0}, {"id": 15.0}))
    result = RegionIntersection((
        SumConstraint("M5.id", ((1.0, "M1.id"), (1.0, "M2.id")), label="tail_kcl"),
    )).build((tail, left, right))
    assert result.retained_count == 2
    assert {(r.values["M5.id"], r.values["M1.id"], r.values["M2.id"]) for r in result.rows} == {
        (20.0, 10.0, 10.0),
        (30.0, 15.0, 15.0),
    }


def test_source_row_correlations_are_preserved():
    m1 = region("M1", ({"w": 1.0, "id": 10.0}, {"w": 2.0, "id": 20.0}))
    result = RegionIntersection().build((m1,))
    assert {(r.values["M1.w"], r.values["M1.id"]) for r in result.rows} == {(1.0, 10.0), (2.0, 20.0)}
    assert result.metadata["source_correlations_preserved"] is True


def test_rejection_diagnostics_count_each_failed_constraint():
    a = region("A", ({"x": 1.0}, {"x": 2.0}))
    b = region("B", ({"x": 3.0},))
    result = RegionIntersection((
        FieldRelationConstraint("A.x", "B.x", label="equal"),
        AllowedValuesConstraint("A.x", frozenset({9.0}), label="allowed"),
    )).build((a, b))
    assert result.is_empty
    assert result.rejected_count == 2
    assert result.metadata["constraint_failure_counts"] == {"equal": 2, "allowed": 2}
    assert all(item.failed_constraints == ("equal", "allowed") for item in result.rejected)


def test_first_failure_policy_stops_diagnostics():
    a = region("A", ({"x": 1.0},))
    b = region("B", ({"x": 2.0},))
    result = RegionIntersection(
        (
            FieldRelationConstraint("A.x", "B.x", label="first"),
            AllowedValuesConstraint("A.x", frozenset({9.0}), label="second"),
        ),
        IntersectionPolicy(collect_all_failures=False),
    ).build((a, b))
    assert result.rejected[0].failed_constraints == ("first",)
    assert result.metadata["constraint_failure_counts"] == {"first": 1, "second": 0}


def test_combination_budget_is_checked_before_enumeration():
    a = region("A", tuple({"x": i} for i in range(10)))
    b = region("B", tuple({"x": i} for i in range(10)))
    with pytest.raises(CombinationBudgetExceededError):
        RegionIntersection(policy=IntersectionPolicy(max_combinations=99)).build((a, b))


def test_duplicate_region_and_constraint_names_are_rejected():
    a = region("A", ({"x": 1.0},))
    with pytest.raises(InvalidRegionError):
        RegionIntersection().build((a, a))
    with pytest.raises(InvalidRegionError):
        RegionIntersection((
            FieldRelationConstraint("A.x", "A.x", label="same"),
            FieldRelationConstraint("A.x", "A.x", label="same"),
        ))


def test_rejection_record_storage_can_be_bounded_without_losing_counts():
    a = region("A", tuple({"x": i} for i in range(5)))
    result = RegionIntersection(
        (AllowedValuesConstraint("A.x", frozenset({99}), label="reject"),),
        IntersectionPolicy(max_retained_rejections=2),
    ).build((a,))
    assert result.rejected_count == 5
    assert len(result.rejected) == 2
    assert result.metadata["retained_rejection_record_count"] == 2
