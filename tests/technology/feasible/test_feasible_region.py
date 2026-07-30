from __future__ import annotations

from openams.technology.adaptive import (
    AdaptiveTableGenerator,
    AxisDomain,
    GenerationPolicy,
    ModelEvaluation,
    SamplingDomain,
)
from openams.technology.feasible import (
    AllowedValuesConstraint,
    BooleanConstraint,
    FeasibleRegionBuilder,
    FeasibleRegionPolicy,
    FieldRelationConstraint,
    RangeConstraint,
)


class FakeModel:
    identity = "fake-continuous-device-v1"

    def evaluate_many(self, coordinates):
        result = []
        for coordinate in coordinates:
            w = coordinate["w"]
            vgs = coordinate["vgs"]
            current = w * max(vgs - 0.4, 0.0) * 10.0
            vdsat = max(vgs - 0.4, 0.0)
            saturated = coordinate["vds"] >= vdsat
            result.append(
                ModelEvaluation(
                    coordinate,
                    {"id": current, "vdsat": vdsat, "mirror_id": current},
                    region="saturation" if saturated else "linear",
                    saturated=saturated,
                )
            )
        return result


def table():
    domain = SamplingDomain((
        AxisDomain("w", 1.0, 3.0, 3),
        AxisDomain("vgs", 0.5, 0.7, 3),
        AxisDomain("vds", 0.1, 0.3, 3),
    ))
    return AdaptiveTableGenerator(FakeModel(), GenerationPolicy(max_points=100)).generate(domain)


def test_range_and_saturation_filter_correlated_rows():
    region = FeasibleRegionBuilder((
        RangeConstraint("id", 2.0, 6.0),
        BooleanConstraint("saturated", True),
    )).build(table())
    assert region.retained_count > 0
    assert all(2.0 <= row["id"] <= 6.0 and row["saturated"] is True for row in region.rows())
    assert all({"w", "vgs", "vds", "id", "vdsat"} <= row.keys() for row in region.rows())
    assert region.metadata["correlations_preserved"] is True


def test_rejection_provenance_collects_all_failed_constraints():
    region = FeasibleRegionBuilder((
        RangeConstraint("id", 100.0, 200.0, label="target_current"),
        BooleanConstraint("saturated", True, label="saturation"),
    )).build(table())
    assert region.is_empty
    assert region.rejected_count == len(table().points)
    assert region.metadata["constraint_failure_counts"]["target_current"] == len(table().points)
    assert any("saturation" in item.failed_constraints for item in region.rejected)


def test_first_failure_policy_stops_after_first_rejection():
    region = FeasibleRegionBuilder(
        (
            RangeConstraint("id", 100.0, 200.0, label="first"),
            BooleanConstraint("saturated", True, label="second"),
        ),
        FeasibleRegionPolicy(collect_all_failures=False),
    ).build(table())
    assert all(item.failed_constraints == ("first",) for item in region.rejected)


def test_allowed_values_constraint_filters_region_label():
    region = FeasibleRegionBuilder((
        AllowedValuesConstraint("region", frozenset({"saturation"})),
    )).build(table())
    assert region.retained_count > 0
    assert all(row["region"] == "saturation" for row in region.rows())


def test_field_relation_constraint_is_generic():
    region = FeasibleRegionBuilder((
        FieldRelationConstraint("id", "mirror_id", absolute_tolerance=0.0),
    )).build(table())
    assert region.retained_count == len(table().points)


def test_builder_can_propose_denser_domain_around_survivors():
    region = FeasibleRegionBuilder(
        (RangeConstraint("id", 3.9, 4.1),),
        FeasibleRegionPolicy(generate_next_domain=True),
    ).build(table())
    assert region.next_sampling_domain is not None
    assert region.next_sampling_domain.point_count >= 1
    original = {axis.name: axis for axis in table().domain.axes}
    refined = {axis.name: axis for axis in region.next_sampling_domain.axes}
    assert refined["w"].minimum >= original["w"].minimum
    assert refined["w"].maximum <= original["w"].maximum


def test_region_can_be_converted_back_to_adaptive_table():
    region = FeasibleRegionBuilder((BooleanConstraint("saturated", True),)).build(table())
    retained_table = region.table()
    assert len(retained_table.points) == region.retained_count
    assert retained_table.metadata["feasible_region"] is True
    assert retained_table.model_identity == table().model_identity
