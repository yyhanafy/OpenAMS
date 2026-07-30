from types import MappingProxyType

import pytest

from openams.technology import (
    CharacterizationPoint,
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    OperatingRegion,
    SignConvention,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyQuantity,
)


def make_operating_point() -> DeviceOperatingPoint:
    return DeviceOperatingPoint(
        model=DeviceModel(
            name="nfet_01v8",
            polarity=DevicePolarity.NMOS,
            voltage_class="1v8",
        ),
        condition=OperatingCondition(
            corner="tt",
            temperature_c=27,
            supply_voltage_v=1.8,
        ),
        length_m=0.5e-6,
        width_m=2e-6,
        vgs_v=0.8,
        vds_v=0.8,
        vbs_v=0.0,
    )


def test_core_records_are_normalized_and_immutable() -> None:
    identity = TechnologyIdentity(
        name="sky130",
        foundry="SkyWater",
        metadata={"source": "open_pdks"},
    )
    point = make_operating_point()

    assert identity.name == "sky130"
    assert isinstance(identity.metadata, MappingProxyType)
    assert point.length_m == 0.5e-6
    assert point.model.polarity is DevicePolarity.NMOS

    with pytest.raises(Exception):
        point.width_m = 4e-6


def test_dimensions_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        DeviceOperatingPoint(
            model=DeviceModel(name="n", polarity=DevicePolarity.NMOS),
            condition=OperatingCondition(corner="tt", temperature_c=27),
            length_m=0,
            width_m=1e-6,
            vgs_v=0.8,
            vds_v=0.8,
        )


def test_capabilities_and_characterization_point() -> None:
    capabilities = TechnologyCapabilities(
        device_kinds={make_operating_point().model.kind},
        polarities={DevicePolarity.NMOS, DevicePolarity.PMOS},
        quantities={TechnologyQuantity.ID, TechnologyQuantity.VDSAT},
        sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
        saturation_classification=True,
        interpolation=True,
    )
    point = CharacterizationPoint(
        operating_point=make_operating_point(),
        values={
            TechnologyQuantity.ID: 15.0e-6,
            TechnologyQuantity.VDSAT: 0.19,
        },
        region=OperatingRegion.SATURATION,
        source="ngspice",
    )

    assert capabilities.interpolation
    assert point.values[TechnologyQuantity.ID] == 15.0e-6


def test_lookup_request_requires_quantities() -> None:
    with pytest.raises(Exception, match="at least one"):
        TechnologyLookupRequest(
            operating_point=make_operating_point(),
            quantities=frozenset(),
        )
