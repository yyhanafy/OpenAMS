import pytest

from openams.technology import (
    TechnologyBackend,
    TechnologyLookupRequest,
    TechnologyQuantity,
)
from openams.technology.table.interpolation import (
    InterpolatingTableTechnologyBackend,
)

from .conftest import make_request_point


def test_backend_satisfies_protocol_and_declares_interpolation(grid_table) -> None:
    backend = InterpolatingTableTechnologyBackend(grid_table)

    assert isinstance(backend, TechnologyBackend)
    assert backend.capabilities.interpolation


def test_backend_exact_lookup_diagnostics(grid_table) -> None:
    backend = InterpolatingTableTechnologyBackend(grid_table)
    request = TechnologyLookupRequest(
        operating_point=grid_table.points[0].operating_point,
        quantities={TechnologyQuantity.ID},
    )
    result = backend.lookup(request)

    assert result.diagnostics["lookup_method"] == "exact_table_match"
    assert result.diagnostics["interpolation_steps"] == 0


def test_backend_interpolation_diagnostics(grid_table) -> None:
    backend = InterpolatingTableTechnologyBackend(grid_table)
    request = TechnologyLookupRequest(
        operating_point=make_request_point(
            grid_table.points[0],
            width_um=1.5,
            vgs_v=0.8,
        ),
        quantities={TechnologyQuantity.ID},
    )
    result = backend.lookup(request)

    assert result.values[TechnologyQuantity.ID] == pytest.approx(15e-6)
    assert result.diagnostics["lookup_method"] == "staged_linear_interpolation"
    assert result.diagnostics["interpolation_steps"] == 3
