"""Operating-region compatibility rules."""

from __future__ import annotations

from openams.technology import OperatingRegion

from .errors import IncompatibleOperatingRegionError


def merge_regions(
    lower: OperatingRegion,
    upper: OperatingRegion,
    *,
    allow_unknown: bool,
) -> OperatingRegion:
    if lower is upper:
        return lower
    if allow_unknown:
        if lower is OperatingRegion.UNKNOWN:
            return upper
        if upper is OperatingRegion.UNKNOWN:
            return lower
    raise IncompatibleOperatingRegionError(
        f"cannot interpolate conflicting regions {lower.value!r} and "
        f"{upper.value!r}"
    )
