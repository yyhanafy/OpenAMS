"""Generic no-extrapolation interpolation over characterization tables."""

from .backend import InterpolatingTableTechnologyBackend
from .errors import (
    IncompatibleOperatingRegionError,
    InterpolationError,
    InterpolationGridError,
    InterpolationOutOfRangeError,
)
from .model import (
    DEFAULT_INTERPOLATION_AXES,
    InterpolationAxis,
    InterpolationPolicy,
    InterpolationStep,
)
from .queries import interpolate_request

__all__ = [
    "DEFAULT_INTERPOLATION_AXES",
    "IncompatibleOperatingRegionError",
    "InterpolatingTableTechnologyBackend",
    "InterpolationAxis",
    "InterpolationError",
    "InterpolationGridError",
    "InterpolationOutOfRangeError",
    "InterpolationPolicy",
    "InterpolationStep",
    "interpolate_request",
]
