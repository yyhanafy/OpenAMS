"""Interpolation algorithm over immutable characterization points."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from openams.technology import (
    CharacterizationPoint,
    DeviceOperatingPoint,
    OperatingRegion,
    TechnologyLookupRequest,
    TechnologyQuantity,
)
from openams.technology.table import CharacterizationTable, exact_point

from ._coordinates import coordinate_value, replace_coordinate
from ._regions import merge_regions
from .errors import (
    InterpolationGridError,
    InterpolationOutOfRangeError,
)
from .model import (
    InterpolationAxis,
    InterpolationPolicy,
    InterpolationStep,
)


def _same_model_context(
    candidate: DeviceOperatingPoint,
    target: DeviceOperatingPoint,
) -> bool:
    return (
        candidate.model == target.model
        and candidate.condition.corner == target.condition.corner
        and candidate.condition.supply_voltage_v
        == target.condition.supply_voltage_v
        and candidate.condition.body_bias_v == target.condition.body_bias_v
    )


def _required_values(
    point: CharacterizationPoint,
    quantities: frozenset[TechnologyQuantity],
) -> dict[TechnologyQuantity, float]:
    missing = quantities - point.values.keys()
    if missing:
        names = sorted(quantity.value for quantity in missing)
        raise InterpolationGridError(
            f"source point is missing requested quantities: {names!r}"
        )
    return {quantity: point.values[quantity] for quantity in quantities}


def _point_signature(
    point: DeviceOperatingPoint,
    *,
    excluding: InterpolationAxis,
) -> tuple[object, ...]:
    values: list[object] = [
        point.model.name,
        point.model.polarity.value,
        point.model.kind.value,
        point.model.voltage_class,
        point.condition.corner,
        point.condition.supply_voltage_v,
        point.condition.body_bias_v,
    ]
    for axis in InterpolationAxis:
        if axis is excluding:
            continue
        values.append(coordinate_value(point, axis))
    return tuple(values)


def _interpolate_pair(
    lower: CharacterizationPoint,
    upper: CharacterizationPoint,
    *,
    axis: InterpolationAxis,
    target_value: float,
    quantities: frozenset[TechnologyQuantity],
    policy: InterpolationPolicy,
) -> tuple[CharacterizationPoint, InterpolationStep]:
    lower_x = coordinate_value(lower.operating_point, axis)
    upper_x = coordinate_value(upper.operating_point, axis)
    if upper_x <= lower_x:
        raise InterpolationGridError(
            f"invalid interpolation bracket on {axis.value!r}"
        )
    alpha = (target_value - lower_x) / (upper_x - lower_x)
    if not 0.0 <= alpha <= 1.0:
        raise InterpolationOutOfRangeError(
            f"target on {axis.value!r} is outside interpolation bracket"
        )

    lower_values = _required_values(lower, quantities)
    upper_values = _required_values(upper, quantities)
    values = {
        quantity: lower_values[quantity]
        + alpha * (upper_values[quantity] - lower_values[quantity])
        for quantity in quantities
    }
    region = merge_regions(
        lower.region,
        upper.region,
        allow_unknown=policy.allow_unknown_region,
    )
    operating_point = replace_coordinate(
        lower.operating_point,
        axis,
        target_value,
    )
    step = InterpolationStep(
        axis=axis,
        target=target_value,
        lower=lower_x,
        upper=upper_x,
        alpha=alpha,
    )
    synthetic = CharacterizationPoint(
        operating_point=operating_point,
        values=values,
        region=region,
        source="linear_interpolation",
        diagnostics={
            "axis": axis.value,
            "lower": lower_x,
            "upper": upper_x,
            "alpha": alpha,
            "lower_source": lower.source,
            "upper_source": upper.source,
        },
        metadata={
            "interpolated": True,
        },
    )
    return synthetic, step


def _collapse_axis(
    points: tuple[CharacterizationPoint, ...],
    *,
    target: DeviceOperatingPoint,
    axis: InterpolationAxis,
    quantities: frozenset[TechnologyQuantity],
    policy: InterpolationPolicy,
) -> tuple[tuple[CharacterizationPoint, ...], tuple[InterpolationStep, ...]]:
    target_value = coordinate_value(target, axis)
    groups: dict[tuple[object, ...], list[CharacterizationPoint]] = defaultdict(list)
    for point in points:
        groups[_point_signature(point.operating_point, excluding=axis)].append(point)

    collapsed: list[CharacterizationPoint] = []
    steps: list[InterpolationStep] = []

    for group in groups.values():
        ordered = sorted(
            group,
            key=lambda point: coordinate_value(point.operating_point, axis),
        )
        exact = next(
            (
                point
                for point in ordered
                if coordinate_value(point.operating_point, axis) == target_value
            ),
            None,
        )
        if exact is not None:
            _required_values(exact, quantities)
            collapsed.append(exact)
            continue

        lower = [
            point
            for point in ordered
            if coordinate_value(point.operating_point, axis) < target_value
        ]
        upper = [
            point
            for point in ordered
            if coordinate_value(point.operating_point, axis) > target_value
        ]
        if not lower or not upper:
            continue

        synthetic, step = _interpolate_pair(
            lower[-1],
            upper[0],
            axis=axis,
            target_value=target_value,
            quantities=quantities,
            policy=policy,
        )
        collapsed.append(synthetic)
        steps.append(step)

    return tuple(collapsed), tuple(steps)


def interpolate_request(
    table: CharacterizationTable,
    request: TechnologyLookupRequest,
    *,
    policy: InterpolationPolicy | None = None,
) -> tuple[CharacterizationPoint, tuple[InterpolationStep, ...]]:
    if not isinstance(table, CharacterizationTable):
        raise TypeError("table must be a CharacterizationTable")
    if not isinstance(request, TechnologyLookupRequest):
        raise TypeError("request must be a TechnologyLookupRequest")
    policy = policy or InterpolationPolicy()
    if not isinstance(policy, InterpolationPolicy):
        raise TypeError("policy must be an InterpolationPolicy")

    exact = exact_point(table, request.operating_point)
    if exact is not None:
        _required_values(exact, request.quantities)
        if (
            request.require_saturation
            and exact.region is not OperatingRegion.SATURATION
        ):
            raise InterpolationGridError(
                "exact point does not satisfy required saturation"
            )
        return exact, ()

    points = tuple(
        point
        for point in table.points
        if _same_model_context(
            point.operating_point,
            request.operating_point,
        )
    )
    if not points:
        raise InterpolationGridError(
            "no characterization points match the requested model context"
        )

    # Exact-coordinate precedence applies per axis, not only to a complete
    # operating-point row.  When the requested coordinate already exists on
    # an axis, discard off-coordinate planes before staged interpolation.
    # This prevents unused branches from affecting diagnostics or provenance.
    current = points
    for axis in policy.axes:
        target_value = coordinate_value(request.operating_point, axis)
        exact_slice = tuple(
            point
            for point in current
            if coordinate_value(point.operating_point, axis) == target_value
        )
        if exact_slice:
            current = exact_slice

    all_steps: list[InterpolationStep] = []
    for axis in policy.axes:
        current, steps = _collapse_axis(
            current,
            target=request.operating_point,
            axis=axis,
            quantities=request.quantities,
            policy=policy,
        )
        all_steps.extend(steps)
        if not current:
            raise InterpolationOutOfRangeError(
                f"request cannot be bracketed on axis {axis.value!r}"
            )

    final = next(
        (
            point
            for point in current
            if point.operating_point == request.operating_point
        ),
        None,
    )
    if final is None:
        raise InterpolationGridError(
            "characterization grid is incomplete for the requested point"
        )

    if (
        request.require_saturation
        and final.region is not OperatingRegion.SATURATION
    ):
        raise InterpolationGridError(
            "interpolated result does not satisfy required saturation"
        )

    return final, tuple(all_steps)
