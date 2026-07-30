from __future__ import annotations

from math import nan

import pytest

from openams.technology.adaptive import (
    AdaptiveTableGenerator,
    AxisDomain,
    AxisSpacing,
    GenerationPolicy,
    ModelEvaluation,
    PointBudgetExceededError,
    RefinementPolicy,
    SamplingDomain,
    coordinate_grid,
    surviving_domain,
)


class FixtureModel:
    identity = "fixture-continuous-model-v1"

    def evaluate_many(self, coordinates):
        result = []
        for point in coordinates:
            width = point["width_um"]
            vgs = point["vgs_v"]
            vds = point["vds_v"]
            current = width * max(vgs - 0.4, 0.0) ** 2 * (1.0 + 0.05 * vds) * 1e-5
            vdsat = max(vgs - 0.4, 0.0)
            result.append(ModelEvaluation(
                coordinates=point,
                quantities={"id_a": current, "vdsat_v": vdsat},
                region="saturation" if vds >= vdsat else "linear",
                saturated=vds >= vdsat,
            ))
        return result


def test_grid_is_exact_and_deterministic():
    domain = SamplingDomain((
        AxisDomain("width_um", 1.0, 2.0, 3),
        AxisDomain("vgs_v", 0.6, 0.8, 2),
    ))
    assert tuple(coordinate_grid(domain)) == (
        {"width_um": 1.0, "vgs_v": 0.6},
        {"width_um": 1.0, "vgs_v": 0.8},
        {"width_um": 1.5, "vgs_v": 0.6},
        {"width_um": 1.5, "vgs_v": 0.8},
        {"width_um": 2.0, "vgs_v": 0.6},
        {"width_um": 2.0, "vgs_v": 0.8},
    )


def test_direct_generation_uses_no_interpolation():
    domain = SamplingDomain((
        AxisDomain("width_um", 1.0, 2.0, 3),
        AxisDomain("vgs_v", 0.6, 0.8, 3),
        AxisDomain("vds_v", 0.2, 0.8, 2),
    ))
    table = AdaptiveTableGenerator(FixtureModel()).generate(domain)
    assert len(table.points) == 18
    assert table.metadata["direct_model_evaluation"] is True
    assert table.metadata["interpolation_used"] is False
    assert table.points[0].source == FixtureModel.identity


def test_saturation_filter_can_be_applied_during_generation():
    domain = SamplingDomain((
        AxisDomain("width_um", 1.0, 1.0, 1),
        AxisDomain("vgs_v", 0.6, 0.8, 3),
        AxisDomain("vds_v", 0.1, 0.8, 3),
    ))
    table = AdaptiveTableGenerator(
        FixtureModel(), GenerationPolicy(require_saturation=True)
    ).generate(domain)
    assert table.points
    assert all(point.saturated for point in table.points)
    assert table.metadata["rejected_region_count"] > 0


def test_point_budget_is_enforced_before_evaluation():
    domain = SamplingDomain((
        AxisDomain("x", 0.0, 1.0, 11),
        AxisDomain("y", 0.0, 1.0, 11),
    ))
    with pytest.raises(PointBudgetExceededError):
        AdaptiveTableGenerator(FixtureModel(), GenerationPolicy(max_points=100)).generate(domain)


def test_refinement_preserves_correlated_surviving_region():
    domain = SamplingDomain((
        AxisDomain("width_um", 1.0, 4.0, 4),
        AxisDomain("vgs_v", 0.5, 0.9, 5),
        AxisDomain("vds_v", 0.2, 1.0, 5),
    ))
    table = AdaptiveTableGenerator(FixtureModel()).generate(domain)
    refined = surviving_domain(
        table,
        lambda row: bool(row["saturated"]) and 0.5e-6 <= float(row["id_a"]) <= 3.0e-6,
        policy=RefinementPolicy(density_multiplier=2),
    )
    assert refined is not None
    assert refined.point_count > 0
    by_name = {axis.name: axis for axis in refined.axes}
    assert by_name["width_um"].minimum >= 1.0
    assert by_name["vgs_v"].maximum <= 0.9


def test_log_axis():
    values = tuple(coordinate_grid(SamplingDomain((
        AxisDomain("current_a", 1e-6, 1e-4, 3, AxisSpacing.LOG),
    ))))
    assert values[0]["current_a"] == pytest.approx(1e-6)
    assert values[1]["current_a"] == pytest.approx(1e-5)
    assert values[2]["current_a"] == pytest.approx(1e-4)
