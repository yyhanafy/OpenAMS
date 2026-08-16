"""Interpolation-layer exceptions."""

from openams.technology.table import TableLookupError


class InterpolationError(TableLookupError):
    """Base class for interpolation failures."""


class InterpolationOutOfRangeError(InterpolationError):
    """Raised when interpolation would require extrapolation."""


class InterpolationGridError(InterpolationError):
    """Raised when a sparse grid cannot support interpolation."""


class IncompatibleOperatingRegionError(InterpolationError):
    """Raised when source regions cannot be interpolated safely."""
