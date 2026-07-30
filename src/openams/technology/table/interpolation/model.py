"""Immutable interpolation configuration and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InterpolationAxis(str, Enum):
    TEMPERATURE = "temperature_c"
    LENGTH = "length_m"
    WIDTH = "width_m"
    VBS = "vbs_v"
    VDS = "vds_v"
    VGS = "vgs_v"


DEFAULT_INTERPOLATION_AXES = (
    InterpolationAxis.TEMPERATURE,
    InterpolationAxis.LENGTH,
    InterpolationAxis.WIDTH,
    InterpolationAxis.VBS,
    InterpolationAxis.VDS,
    InterpolationAxis.VGS,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class InterpolationPolicy:
    axes: tuple[InterpolationAxis, ...] = DEFAULT_INTERPOLATION_AXES
    allow_unknown_region: bool = True

    def __post_init__(self) -> None:
        axes = tuple(self.axes)
        if not axes:
            raise ValueError("interpolation policy requires at least one axis")
        if len(set(axes)) != len(axes):
            raise ValueError("interpolation axes must be unique")
        if not all(isinstance(axis, InterpolationAxis) for axis in axes):
            raise TypeError("axes must contain InterpolationAxis values")
        if not isinstance(self.allow_unknown_region, bool):
            raise TypeError("allow_unknown_region must be boolean")
        object.__setattr__(self, "axes", axes)


@dataclass(frozen=True, slots=True, kw_only=True)
class InterpolationStep:
    axis: InterpolationAxis
    target: float
    lower: float
    upper: float
    alpha: float

    def __post_init__(self) -> None:
        if not isinstance(self.axis, InterpolationAxis):
            raise TypeError("axis must be an InterpolationAxis")
        if self.upper <= self.lower:
            raise ValueError("upper interpolation coordinate must exceed lower")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError("interpolation alpha must be within [0, 1]")
