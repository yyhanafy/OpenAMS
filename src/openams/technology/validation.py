"""Structural validation entry points for technology records."""

from __future__ import annotations

from .errors import TechnologyValidationError
from .model import (
    CharacterizationPoint,
    OperatingRegion,
    TechnologyLookupRequest,
    TechnologyLookupResult,
)


def validate_lookup_request(
    request: TechnologyLookupRequest,
) -> TechnologyLookupRequest:
    if not isinstance(request, TechnologyLookupRequest):
        raise TypeError("request must be a TechnologyLookupRequest")
    return request


def validate_lookup_result(
    result: TechnologyLookupResult,
) -> TechnologyLookupResult:
    if not isinstance(result, TechnologyLookupResult):
        raise TypeError("result must be a TechnologyLookupResult")

    missing = result.request.quantities - result.values.keys()
    if missing:
        names = sorted(quantity.value for quantity in missing)
        raise TechnologyValidationError(
            f"lookup result is missing requested quantities: {names!r}"
        )

    if (
        result.request.require_saturation
        and result.region is not OperatingRegion.SATURATION
    ):
        raise TechnologyValidationError(
            "lookup result does not satisfy required saturation"
        )

    return result


def validate_characterization_point(
    point: CharacterizationPoint,
) -> CharacterizationPoint:
    if not isinstance(point, CharacterizationPoint):
        raise TypeError("point must be a CharacterizationPoint")
    return point
