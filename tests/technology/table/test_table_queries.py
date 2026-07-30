from openams.technology import DeviceOperatingPoint
from openams.technology.table import (
    BracketAxis,
    bracket_points,
    exact_point,
    nearest_points,
    points_for_model,
)


def replace_operating_point(
    point,
    *,
    width_m=None,
    vgs_v=None,
):
    source = point.operating_point
    return DeviceOperatingPoint(
        model=source.model,
        condition=source.condition,
        length_m=source.length_m,
        width_m=source.width_m if width_m is None else width_m,
        vgs_v=source.vgs_v if vgs_v is None else vgs_v,
        vds_v=source.vds_v,
        vbs_v=source.vbs_v,
    )


def test_exact_and_model_queries(characterization_table) -> None:
    target = characterization_table.points[1].operating_point
    assert exact_point(characterization_table, target) is characterization_table.points[1]
    assert len(points_for_model(characterization_table, target)) == 4


def test_nearest_points_are_deterministic(characterization_table) -> None:
    target = replace_operating_point(
        characterization_table.points[1],
        width_m=2.2e-6,
    )
    nearest = nearest_points(characterization_table, target, limit=2)

    assert nearest[0] is characterization_table.points[1]
    assert nearest[1] is characterization_table.points[0]


def test_width_bracketing(characterization_table) -> None:
    target = replace_operating_point(
        characterization_table.points[1],
        width_m=3.0e-6,
    )
    bracket = bracket_points(
        characterization_table,
        target,
        BracketAxis.WIDTH,
    )

    assert bracket.lower is characterization_table.points[1]
    assert bracket.upper is characterization_table.points[2]
    assert bracket.is_complete
    assert not bracket.is_exact


def test_bracketing_requires_exact_other_axes(characterization_table) -> None:
    target = replace_operating_point(
        characterization_table.points[1],
        width_m=3.0e-6,
        vgs_v=0.9,
    )
    bracket = bracket_points(
        characterization_table,
        target,
        BracketAxis.WIDTH,
    )

    assert bracket.lower is characterization_table.points[3]
    assert bracket.upper is None
