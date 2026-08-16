"""Deterministic queries over immutable characterization tables."""

from __future__ import annotations

import math
from collections.abc import Iterable

from openams.technology import CharacterizationPoint, DeviceOperatingPoint

from ._keys import (
    coordinate_value,
    exact_characterization_key,
    exact_operating_point_key,
    model_condition_key,
)
from .model import BracketAxis, BracketResult, CharacterizationTable


_DISTANCE_AXES = (
    "length_m",
    "width_m",
    "vgs_v",
    "vds_v",
    "vbs_v",
    "temperature_c",
)


def points_for_model(
    table: CharacterizationTable,
    operating_point: DeviceOperatingPoint,
) -> tuple[CharacterizationPoint, ...]:
    if not isinstance(table, CharacterizationTable):
        raise TypeError("table must be a CharacterizationTable")
    if not isinstance(operating_point, DeviceOperatingPoint):
        raise TypeError("operating_point must be a DeviceOperatingPoint")

    target_key = model_condition_key(operating_point)
    return tuple(
        point
        for point in table.points
        if model_condition_key(point.operating_point) == target_key
    )


def exact_point(
    table: CharacterizationTable,
    operating_point: DeviceOperatingPoint,
) -> CharacterizationPoint | None:
    if not isinstance(table, CharacterizationTable):
        raise TypeError("table must be a CharacterizationTable")
    if not isinstance(operating_point, DeviceOperatingPoint):
        raise TypeError("operating_point must be a DeviceOperatingPoint")

    target = exact_operating_point_key(operating_point)
    for point in table.points:
        if exact_characterization_key(point) == target:
            return point
    return None


def _axis_target(
    operating_point: DeviceOperatingPoint,
    axis: str,
) -> float:
    if axis == "temperature_c":
        return operating_point.condition.temperature_c
    return float(getattr(operating_point, axis))


def _normalized_distance(
    point: CharacterizationPoint,
    target: DeviceOperatingPoint,
    spans: dict[str, float],
) -> float:
    total = 0.0
    for axis in _DISTANCE_AXES:
        span = spans[axis]
        if span == 0.0:
            continue
        delta = (
            coordinate_value(point, axis) - _axis_target(target, axis)
        ) / span
        total += delta * delta
    return math.sqrt(total)


def nearest_points(
    table: CharacterizationTable,
    operating_point: DeviceOperatingPoint,
    *,
    limit: int = 1,
) -> tuple[CharacterizationPoint, ...]:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")

    candidates = points_for_model(table, operating_point)
    if not candidates:
        return ()

    spans: dict[str, float] = {}
    for axis in _DISTANCE_AXES:
        values = [coordinate_value(point, axis) for point in candidates]
        spans[axis] = max(values) - min(values)

    indexed = tuple(enumerate(candidates))
    ordered = sorted(
        indexed,
        key=lambda item: (
            _normalized_distance(item[1], operating_point, spans),
            item[0],
        ),
    )
    return tuple(point for _, point in ordered[:limit])


def _matches_other_axes(
    candidate: CharacterizationPoint,
    target: DeviceOperatingPoint,
    bracket_axis: BracketAxis,
) -> bool:
    candidate_op = candidate.operating_point

    if model_condition_key(candidate_op) != model_condition_key(target):
        return False

    if candidate_op.condition.supply_voltage_v != target.condition.supply_voltage_v:
        return False
    if candidate_op.condition.body_bias_v != target.condition.body_bias_v:
        return False

    for axis in _DISTANCE_AXES:
        if axis == bracket_axis.value:
            continue
        if coordinate_value(candidate, axis) != _axis_target(target, axis):
            return False
    return True


def bracket_points(
    table: CharacterizationTable,
    operating_point: DeviceOperatingPoint,
    axis: BracketAxis,
) -> BracketResult:
    if not isinstance(table, CharacterizationTable):
        raise TypeError("table must be a CharacterizationTable")
    if not isinstance(operating_point, DeviceOperatingPoint):
        raise TypeError("operating_point must be a DeviceOperatingPoint")
    if not isinstance(axis, BracketAxis):
        raise TypeError("axis must be a BracketAxis")

    target = _axis_target(operating_point, axis.value)
    candidates = tuple(
        point
        for point in table.points
        if _matches_other_axes(point, operating_point, axis)
    )

    exact = next(
        (
            point
            for point in candidates
            if coordinate_value(point, axis.value) == target
        ),
        None,
    )
    if exact is not None:
        return BracketResult(
            axis=axis,
            target=target,
            lower=exact,
            upper=exact,
        )

    lower_candidates = tuple(
        point
        for point in candidates
        if coordinate_value(point, axis.value) < target
    )
    upper_candidates = tuple(
        point
        for point in candidates
        if coordinate_value(point, axis.value) > target
    )

    lower = (
        max(
            lower_candidates,
            key=lambda point: coordinate_value(point, axis.value),
        )
        if lower_candidates
        else None
    )
    upper = (
        min(
            upper_candidates,
            key=lambda point: coordinate_value(point, axis.value),
        )
        if upper_candidates
        else None
    )

    return BracketResult(
        axis=axis,
        target=target,
        lower=lower,
        upper=upper,
    )
