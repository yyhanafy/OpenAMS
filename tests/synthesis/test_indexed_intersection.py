from __future__ import annotations

import pytest

from openams.synthesis import (
    FieldRelationConstraint,
    IntersectionPlanner,
    InvalidRegionError,
    PlannedIntersectionPolicy,
    PlannedRegionIntersection,
    RegionInput,
    RegionIntersection,
    SumConstraint,
)


def region(name, rows):
    return RegionInput(name, tuple(rows))


def test_planner_builds_exact_equality_join_plan():
    a = region("A", ({"x": 1.0}, {"x": 2.0}))
    b = region("B", ({"x": 1.0}, {"x": 3.0}))
    constraint = FieldRelationConstraint("A.x", "B.x", label="equal")
    plan = IntersectionPlanner().plan((a, b), (constraint,))
    assert plan.uses_indexed_joins
    assert plan.indexable_constraint_names == ("equal",)
    assert plan.steps[0].incoming_region in {"A", "B"}


def test_tolerance_relation_is_not_used_as_hash_key():
    a = region("A", ({"x": 1.0},))
    b = region("B", ({"x": 1.001},))
    constraint = FieldRelationConstraint("A.x", "B.x", absolute_tolerance=0.01, label="near")
    plan = IntersectionPlanner().plan((a, b), (constraint,))
    assert not plan.uses_indexed_joins
    assert plan.fallback_reason is not None


def test_indexed_and_cartesian_results_match_for_mirror_join():
    m3 = region("M3", tuple({"id": float(i), "w": float(i * 2)} for i in range(100)))
    m4 = region("M4", tuple({"id": float(i), "w": float(i * 2)} for i in range(0, 100, 2)))
    constraints = (
        FieldRelationConstraint("M3.id", "M4.id", label="current"),
        FieldRelationConstraint("M3.w", "M4.w", label="width"),
    )
    indexed = PlannedRegionIntersection(constraints).build((m3, m4))
    cartesian = RegionIntersection(constraints).build((m3, m4))
    assert indexed.dictionaries() == cartesian.dictionaries()
    assert indexed.metadata["intersection_method"] == "planned_indexed_equality_join"
    assert indexed.metadata["indexed_materialized_candidate_count"] == 50
    assert indexed.metadata["candidate_combination_count"] == 5000


def test_three_region_chain_is_joined_incrementally():
    a = region("A", ({"x": 1}, {"x": 2}))
    b = region("B", ({"x": 1}, {"x": 2}, {"x": 3}))
    c = region("C", ({"x": 2}, {"x": 4}))
    constraints = (
        FieldRelationConstraint("A.x", "B.x", label="ab"),
        FieldRelationConstraint("B.x", "C.x", label="bc"),
    )
    result = PlannedRegionIntersection(constraints).build((a, b, c))
    assert result.retained_count == 1
    assert result.rows[0].values["A.x"] == 2
    assert result.rows[0].values["C.x"] == 2


def test_residual_constraint_is_evaluated_after_indexed_join():
    a = region("A", ({"x": 1, "y": 2}, {"x": 2, "y": 5}))
    b = region("B", ({"x": 1}, {"x": 2}))
    constraints = (
        FieldRelationConstraint("A.x", "B.x", label="key"),
        FieldRelationConstraint("A.y", "B.x", scale=2.0, label="residual"),
    )
    result = PlannedRegionIntersection(constraints).build((a, b))
    assert result.retained_count == 1
    assert result.rows[0].values["A.x"] == 1
    assert result.metadata["residual_constraint_names"] == ("residual",)


def test_kcl_only_join_falls_back_to_cartesian():
    tail = region("T", ({"id": 2.0},))
    a = region("A", ({"id": 1.0},))
    b = region("B", ({"id": 1.0},))
    result = PlannedRegionIntersection((
        SumConstraint("T.id", ((1.0, "A.id"), (1.0, "B.id")), label="kcl"),
    )).build((tail, a, b))
    assert result.retained_count == 1
    assert result.metadata["intersection_method"] == "explicit_cartesian_filter"
    assert "not all input regions" in result.metadata["plan_fallback_reason"]


def test_complete_rejection_diagnostics_request_forces_fallback():
    a = region("A", ({"x": 1}, {"x": 2}))
    b = region("B", ({"x": 1}, {"x": 3}))
    constraint = FieldRelationConstraint("A.x", "B.x", label="equal")
    result = PlannedRegionIntersection(
        (constraint,),
        PlannedIntersectionPolicy(require_complete_rejection_diagnostics=True),
    ).build((a, b))
    assert result.metadata["intersection_method"] == "explicit_cartesian_filter"
    assert result.metadata["plan_fallback_reason"] == "complete rejection diagnostics requested"
    assert len(result.rejected) == 3


def test_unplannable_can_be_configured_as_error():
    a = region("A", ({"x": 1.0},))
    b = region("B", ({"x": 1.0},))
    with pytest.raises(InvalidRegionError, match="indexed intersection unavailable"):
        PlannedRegionIntersection(
            (), PlannedIntersectionPolicy(fallback_on_unplannable=False)
        ).build((a, b))
