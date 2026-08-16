"""Operating-point coordinate helpers for interpolation."""

from __future__ import annotations

from openams.technology import DeviceOperatingPoint, OperatingCondition

from .model import InterpolationAxis


def coordinate_value(
    point: DeviceOperatingPoint,
    axis: InterpolationAxis,
) -> float:
    if axis is InterpolationAxis.TEMPERATURE:
        return point.condition.temperature_c
    return float(getattr(point, axis.value))


def replace_coordinate(
    point: DeviceOperatingPoint,
    axis: InterpolationAxis,
    value: float,
) -> DeviceOperatingPoint:
    condition = point.condition
    if axis is InterpolationAxis.TEMPERATURE:
        condition = OperatingCondition(
            corner=condition.corner,
            temperature_c=value,
            supply_voltage_v=condition.supply_voltage_v,
            body_bias_v=condition.body_bias_v,
            metadata=condition.metadata,
        )

    values = {
        "model": point.model,
        "condition": condition,
        "length_m": point.length_m,
        "width_m": point.width_m,
        "vgs_v": point.vgs_v,
        "vds_v": point.vds_v,
        "vbs_v": point.vbs_v,
    }
    if axis is not InterpolationAxis.TEMPERATURE:
        values[axis.value] = value
    return DeviceOperatingPoint(**values)
