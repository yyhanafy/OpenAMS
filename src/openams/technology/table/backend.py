"""Exact-lookup implementation of the technology backend protocol."""

from __future__ import annotations

from openams.technology import (
    OperatingRegion,
    TechnologyBackend,
    TechnologyCapabilityError,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyLookupResult,
    missing_capabilities,
    validate_lookup_result,
)

from .errors import TableLookupError
from .model import CharacterizationTable
from .queries import exact_point
from .validation import validate_characterization_table


class TableTechnologyBackend:
    """Technology backend providing exact table lookup only."""

    def __init__(self, table: CharacterizationTable) -> None:
        self._table = validate_characterization_table(table)

    @property
    def table(self) -> CharacterizationTable:
        return self._table

    @property
    def identity(self) -> TechnologyIdentity:
        return self._table.identity

    @property
    def capabilities(self) -> TechnologyCapabilities:
        return self._table.capabilities

    def lookup(
        self,
        request: TechnologyLookupRequest,
    ) -> TechnologyLookupResult:
        missing = missing_capabilities(self.capabilities, request)
        if missing:
            raise TechnologyCapabilityError(
                f"table backend lacks capabilities: {sorted(missing)!r}"
            )

        point = exact_point(self._table, request.operating_point)
        if point is None:
            raise TableLookupError(
                "exact operating point is not present in the characterization table"
            )

        missing_quantities = request.quantities - point.values.keys()
        if missing_quantities:
            names = sorted(
                quantity.value for quantity in missing_quantities
            )
            raise TableLookupError(
                f"exact point is missing requested quantities: {names!r}"
            )

        if (
            request.require_saturation
            and point.region is not OperatingRegion.SATURATION
        ):
            raise TableLookupError(
                "exact point does not satisfy required saturation"
            )

        result = TechnologyLookupResult(
            request=request,
            values={
                quantity: point.values[quantity]
                for quantity in request.quantities
            },
            region=point.region,
            backend=self.identity,
            diagnostics={
                "lookup_method": "exact_table_match",
                "source": point.source,
            },
            metadata=point.metadata,
        )
        return validate_lookup_result(result)


assert isinstance(TableTechnologyBackend, type)
