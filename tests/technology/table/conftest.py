import pytest

from openams.technology import (
    CharacterizationPoint,
    DeviceKind,
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    OperatingRegion,
    SignConvention,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyQuantity,
)
from openams.technology.table import CharacterizationTable


@pytest.fixture
def nfet_model() -> DeviceModel:
    return DeviceModel(
        name="nfet_01v8",
        polarity=DevicePolarity.NMOS,
        voltage_class="1v8",
    )


def make_point(
    model: DeviceModel,
    *,
    width_um: float,
    vgs_v: float = 0.8,
    vds_v: float = 0.8,
    temperature_c: float = 27.0,
    current_ua: float,
) -> CharacterizationPoint:
    return CharacterizationPoint(
        operating_point=DeviceOperatingPoint(
            model=model,
            condition=OperatingCondition(
                corner="tt",
                temperature_c=temperature_c,
                supply_voltage_v=1.8,
            ),
            length_m=0.5e-6,
            width_m=width_um * 1e-6,
            vgs_v=vgs_v,
            vds_v=vds_v,
            vbs_v=0.0,
        ),
        values={
            TechnologyQuantity.ID: current_ua * 1e-6,
            TechnologyQuantity.VDSAT: 0.19,
        },
        region=OperatingRegion.SATURATION,
        source="fixture",
    )


@pytest.fixture
def characterization_table(nfet_model: DeviceModel) -> CharacterizationTable:
    points = (
        make_point(nfet_model, width_um=1.0, current_ua=7.0),
        make_point(nfet_model, width_um=2.0, current_ua=15.0),
        make_point(nfet_model, width_um=4.0, current_ua=34.0),
        make_point(
            nfet_model,
            width_um=2.0,
            vgs_v=0.9,
            current_ua=27.0,
        ),
    )
    return CharacterizationTable(
        identity=TechnologyIdentity(
            name="fixture",
            model_version="1",
        ),
        capabilities=TechnologyCapabilities(
            device_kinds={DeviceKind.MOS},
            polarities={DevicePolarity.NMOS},
            quantities={
                TechnologyQuantity.ID,
                TechnologyQuantity.VDSAT,
            },
            sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
            saturation_classification=True,
            interpolation=False,
        ),
        points=points,
    )
