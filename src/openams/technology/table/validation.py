"""Validation for generic characterization tables."""

from __future__ import annotations

from openams.technology import CharacterizationPoint

from .errors import TableValidationError
from .model import CharacterizationTable


def _validate_point_capabilities(
    table: CharacterizationTable,
    point: CharacterizationPoint,
) -> None:
    capabilities = table.capabilities
    operating_point = point.operating_point
    model = operating_point.model

    if model.kind not in capabilities.device_kinds:
        raise TableValidationError(
            f"unsupported device kind {model.kind.value!r}"
        )
    if model.polarity not in capabilities.polarities:
        raise TableValidationError(
            f"unsupported device polarity {model.polarity.value!r}"
        )

    unsupported = point.values.keys() - capabilities.quantities
    if unsupported:
        names = sorted(quantity.value for quantity in unsupported)
        raise TableValidationError(
            f"point contains undeclared quantities: {names!r}"
        )


def validate_characterization_table(
    table: CharacterizationTable,
) -> CharacterizationTable:
    if not isinstance(table, CharacterizationTable):
        raise TypeError("table must be a CharacterizationTable")

    for point in table.points:
        _validate_point_capabilities(table, point)

    return table
