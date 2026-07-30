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
def model() -> DeviceModel:
    return DeviceModel(name="nfet", polarity=DevicePolarity.NMOS)


def make_point(
    model: DeviceModel,
    *,
    width_um: float,
    vgs_v: float,
    current_ua: float,
    region: OperatingRegion = OperatingRegion.SATURATION,
) -> CharacterizationPoint:
    return CharacterizationPoint(
        operating_point=DeviceOperatingPoint(
            model=model,
            condition=OperatingCondition(
                corner="tt",
                temperature_c=27.0,
                supply_voltage_v=1.8,
            ),
            length_m=0.5e-6,
            width_m=width_um * 1e-6,
            vgs_v=vgs_v,
            vds_v=0.8,
            vbs_v=0.0,
        ),
        values={
            TechnologyQuantity.ID: current_ua * 1e-6,
            TechnologyQuantity.GM: current_ua * 10e-6,
        },
        region=region,
        source="fixture",
    )


@pytest.fixture
def grid_table(model: DeviceModel) -> CharacterizationTable:
    points = (
        make_point(model, width_um=1.0, vgs_v=0.7, current_ua=5.0),
        make_point(model, width_um=2.0, vgs_v=0.7, current_ua=10.0),
        make_point(model, width_um=1.0, vgs_v=0.9, current_ua=15.0),
        make_point(model, width_um=2.0, vgs_v=0.9, current_ua=30.0),
    )
    return CharacterizationTable(
        identity=TechnologyIdentity(name="fixture"),
        capabilities=TechnologyCapabilities(
            device_kinds={DeviceKind.MOS},
            polarities={DevicePolarity.NMOS},
            quantities={TechnologyQuantity.ID, TechnologyQuantity.GM},
            sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
            saturation_classification=True,
            interpolation=False,
        ),
        points=points,
    )


def make_request_point(
    source: CharacterizationPoint,
    *,
    width_um: float,
    vgs_v: float,
) -> DeviceOperatingPoint:
    point = source.operating_point
    return DeviceOperatingPoint(
        model=point.model,
        condition=point.condition,
        length_m=point.length_m,
        width_m=width_um * 1e-6,
        vgs_v=vgs_v,
        vds_v=point.vds_v,
        vbs_v=point.vbs_v,
    )
