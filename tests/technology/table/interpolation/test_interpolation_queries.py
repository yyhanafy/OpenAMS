import pytest

from openams.technology import (
    OperatingRegion,
    TechnologyLookupRequest,
    TechnologyQuantity,
)
from openams.technology.table import CharacterizationTable
from openams.technology.table.interpolation import (
    IncompatibleOperatingRegionError,
    InterpolationGridError,
    InterpolationOutOfRangeError,
    interpolate_request,
)

from .conftest import make_point, make_request_point


def test_exact_point_precedes_interpolation(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=grid_table.points[0].operating_point,
        quantities={TechnologyQuantity.ID},
    )
    point, steps = interpolate_request(grid_table, request)

    assert point is grid_table.points[0]
    assert steps == ()


def test_one_axis_interpolation(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=1.5,
            vgs_v=0.7,
        ),
        quantities={TechnologyQuantity.ID},
        require_saturation=True,
    )
    point, steps = interpolate_request(grid_table, request)

    assert point.values[TechnologyQuantity.ID] == pytest.approx(7.5e-6)
    assert len(steps) == 1
    assert steps[0].alpha == pytest.approx(0.5)


def test_two_axis_staged_interpolation(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=1.5,
            vgs_v=0.8,
        ),
        quantities={TechnologyQuantity.ID, TechnologyQuantity.GM},
    )
    point, steps = interpolate_request(grid_table, request)

    assert point.values[TechnologyQuantity.ID] == pytest.approx(15e-6)
    assert point.values[TechnologyQuantity.GM] == pytest.approx(150e-6)
    assert len(steps) == 3


def test_out_of_range_is_not_extrapolated(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=3.0,
            vgs_v=0.8,
        ),
        quantities={TechnologyQuantity.ID},
    )
    with pytest.raises(InterpolationOutOfRangeError):
        interpolate_request(grid_table, request)


def test_sparse_grid_is_rejected(grid_table) -> None:
    sparse = CharacterizationTable(
        identity=grid_table.identity,
        capabilities=grid_table.capabilities,
        points=grid_table.points[:-1],
    )
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            sparse.points[0],
            width_um=1.5,
            vgs_v=0.8,
        ),
        quantities={TechnologyQuantity.ID},
    )
    with pytest.raises((InterpolationGridError, InterpolationOutOfRangeError)):
        interpolate_request(sparse, request)


def test_conflicting_regions_are_rejected(grid_table, model) -> None:
    conflicting = CharacterizationTable(
        identity=grid_table.identity,
        capabilities=grid_table.capabilities,
        points=(
            make_point(
                model,
                width_um=1.0,
                vgs_v=0.7,
                current_ua=5.0,
                region=OperatingRegion.LINEAR,
            ),
            make_point(
                model,
                width_um=2.0,
                vgs_v=0.7,
                current_ua=10.0,
                region=OperatingRegion.SATURATION,
            ),
        ),
    )
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            conflicting.points[0],
            width_um=1.5,
            vgs_v=0.7,
        ),
        quantities={TechnologyQuantity.ID},
    )
    with pytest.raises(IncompatibleOperatingRegionError):
        interpolate_request(conflicting, request)

def test_grouping_key_ignores_unhashable_model_metadata(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=1.5,
            vgs_v=0.7,
        ),
        quantities={TechnologyQuantity.ID},
    )

    point, steps = interpolate_request(grid_table, request)

    assert point.values[TechnologyQuantity.ID] == pytest.approx(7.5e-6)
    assert len(steps) == 1

def test_exact_coordinate_plane_is_pruned_before_other_axes(grid_table) -> None:
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=1.5,
            vgs_v=0.7,
        ),
        quantities={TechnologyQuantity.ID},
    )

    _, steps = interpolate_request(grid_table, request)

    assert len(steps) == 1
    assert steps[0].axis.value == "width_m"

