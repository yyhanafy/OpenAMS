import pytest

from openams.technology import (
    DeviceOperatingPoint,
    TechnologyBackend,
    TechnologyLookupRequest,
    TechnologyQuantity,
)
from openams.technology.table import (
    TableLookupError,
    TableTechnologyBackend,
)


def test_backend_satisfies_protocol(characterization_table) -> None:
    backend = TableTechnologyBackend(characterization_table)
    assert isinstance(backend, TechnologyBackend)
    assert backend.identity is characterization_table.identity


def test_exact_backend_lookup(characterization_table) -> None:
    backend = TableTechnologyBackend(characterization_table)
    request = TechnologyLookupRequest(
        operating_point=characterization_table.points[1].operating_point,
        quantities={TechnologyQuantity.ID, TechnologyQuantity.VDSAT},
        require_saturation=True,
    )
    result = backend.lookup(request)

    assert result.values[TechnologyQuantity.ID] == pytest.approx(15e-6)
    assert result.diagnostics["lookup_method"] == "exact_table_match"


def test_backend_does_not_interpolate(characterization_table) -> None:
    backend = TableTechnologyBackend(characterization_table)
    source = characterization_table.points[1].operating_point
    missing_point = DeviceOperatingPoint(
        model=source.model,
        condition=source.condition,
        length_m=source.length_m,
        width_m=3e-6,
        vgs_v=source.vgs_v,
        vds_v=source.vds_v,
        vbs_v=source.vbs_v,
    )
    request = TechnologyLookupRequest(
        operating_point=missing_point,
        quantities={TechnologyQuantity.ID},
    )

    with pytest.raises(TableLookupError, match="exact operating point"):
        backend.lookup(request)
