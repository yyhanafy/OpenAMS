"""Stable keys and coordinate access for characterization points."""

from __future__ import annotations

from typing import TypeAlias

from openams.technology import CharacterizationPoint, DeviceOperatingPoint

ExactPointKey: TypeAlias = tuple[
    str,
    str,
    str,
    str,
    float,
    float | None,
    float | None,
    float,
    float,
    float,
    float,
    float,
]


def exact_operating_point_key(point: DeviceOperatingPoint) -> ExactPointKey:
    condition = point.condition
    model = point.model
    return (
        model.name,
        model.polarity.value,
        model.kind.value,
        condition.corner,
        condition.temperature_c,
        condition.supply_voltage_v,
        condition.body_bias_v,
        point.length_m,
        point.width_m,
        point.vgs_v,
        point.vds_v,
        point.vbs_v,
    )


def exact_characterization_key(point: CharacterizationPoint) -> ExactPointKey:
    return exact_operating_point_key(point.operating_point)


def model_condition_key(point: DeviceOperatingPoint) -> tuple[str, str, str, str]:
    return (
        point.model.name,
        point.model.polarity.value,
        point.model.kind.value,
        point.condition.corner,
    )


def coordinate_value(point: CharacterizationPoint, axis: str) -> float:
    operating_point = point.operating_point
    if axis == "temperature_c":
        return operating_point.condition.temperature_c
    return float(getattr(operating_point, axis))
