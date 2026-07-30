import pytest

from openams.technology import (
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    OperatingRegion,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyLookupResult,
    TechnologyQuantity,
    TechnologyValidationError,
    result_quantity,
    validate_lookup_result,
)


def make_request(*, require_saturation: bool = False) -> TechnologyLookupRequest:
    return TechnologyLookupRequest(
        operating_point=DeviceOperatingPoint(
            model=DeviceModel(name="nfet", polarity=DevicePolarity.NMOS),
            condition=OperatingCondition(corner="tt", temperature_c=27),
            length_m=0.5e-6,
            width_m=2e-6,
            vgs_v=0.8,
            vds_v=0.8,
        ),
        quantities={TechnologyQuantity.ID, TechnologyQuantity.VDSAT},
        require_saturation=require_saturation,
    )


def test_result_requires_every_requested_quantity() -> None:
    result = TechnologyLookupResult(
        request=make_request(),
        values={TechnologyQuantity.ID: 10e-6},
        region=OperatingRegion.SATURATION,
        backend=TechnologyIdentity(name="test"),
    )

    with pytest.raises(TechnologyValidationError, match="missing"):
        validate_lookup_result(result)


def test_saturation_requirement_is_verified() -> None:
    result = TechnologyLookupResult(
        request=make_request(require_saturation=True),
        values={
            TechnologyQuantity.ID: 10e-6,
            TechnologyQuantity.VDSAT: 0.2,
        },
        region=OperatingRegion.LINEAR,
        backend=TechnologyIdentity(name="test"),
    )

    with pytest.raises(TechnologyValidationError, match="saturation"):
        validate_lookup_result(result)


def test_result_quantity_query() -> None:
    result = TechnologyLookupResult(
        request=make_request(),
        values={
            TechnologyQuantity.ID: 10e-6,
            TechnologyQuantity.VDSAT: 0.2,
        },
        region=OperatingRegion.SATURATION,
        backend=TechnologyIdentity(name="test"),
    )

    assert result_quantity(result, TechnologyQuantity.VDSAT) == 0.2
