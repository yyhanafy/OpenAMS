"""Capability and result queries."""

from __future__ import annotations

from .errors import TechnologyCapabilityError
from .model import (
    TechnologyCapabilities,
    TechnologyLookupRequest,
    TechnologyLookupResult,
    TechnologyQuantity,
)


def missing_capabilities(
    capabilities: TechnologyCapabilities,
    request: TechnologyLookupRequest,
) -> frozenset[str]:
    """Return stable descriptions of capabilities missing for a request."""

    if not isinstance(capabilities, TechnologyCapabilities):
        raise TypeError("capabilities must be TechnologyCapabilities")
    if not isinstance(request, TechnologyLookupRequest):
        raise TypeError("request must be TechnologyLookupRequest")

    missing: set[str] = set()
    operating_point = request.operating_point

    if operating_point.model.kind not in capabilities.device_kinds:
        missing.add(f"device_kind:{operating_point.model.kind.value}")
    if operating_point.model.polarity not in capabilities.polarities:
        missing.add(f"polarity:{operating_point.model.polarity.value}")

    for quantity in request.quantities - capabilities.quantities:
        missing.add(f"quantity:{quantity.value}")

    if request.require_saturation and not capabilities.saturation_classification:
        missing.add("saturation_classification")

    return frozenset(missing)


def supports_request(
    capabilities: TechnologyCapabilities,
    request: TechnologyLookupRequest,
) -> bool:
    """Return whether declared capabilities can satisfy a request."""

    return not missing_capabilities(capabilities, request)


def result_quantity(
    result: TechnologyLookupResult,
    quantity: TechnologyQuantity,
) -> float:
    """Return one result quantity or raise a technology capability error."""

    if not isinstance(result, TechnologyLookupResult):
        raise TypeError("result must be TechnologyLookupResult")
    if not isinstance(quantity, TechnologyQuantity):
        raise TypeError("quantity must be TechnologyQuantity")
    try:
        return result.values[quantity]
    except KeyError as exc:
        raise TechnologyCapabilityError(
            f"lookup result does not contain quantity {quantity.value!r}"
        ) from exc
