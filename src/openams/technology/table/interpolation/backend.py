"""Interpolating implementation of the technology backend protocol."""

from __future__ import annotations

from openams.technology import (
    TechnologyBackend,
    TechnologyCapabilityError,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyLookupResult,
    missing_capabilities,
    validate_lookup_result,
)
from openams.technology.table import CharacterizationTable
from openams.technology.table.validation import validate_characterization_table

from .model import InterpolationPolicy
from .queries import interpolate_request


class InterpolatingTableTechnologyBackend:
    """Exact-first, no-extrapolation table interpolation backend."""

    def __init__(
        self,
        table: CharacterizationTable,
        *,
        policy: InterpolationPolicy | None = None,
    ) -> None:
        self._table = validate_characterization_table(table)
        self._policy = policy or InterpolationPolicy()

    @property
    def table(self) -> CharacterizationTable:
        return self._table

    @property
    def policy(self) -> InterpolationPolicy:
        return self._policy

    @property
    def identity(self) -> TechnologyIdentity:
        return self._table.identity

    @property
    def capabilities(self) -> TechnologyCapabilities:
        return TechnologyCapabilities(
            device_kinds=self._table.capabilities.device_kinds,
            polarities=self._table.capabilities.polarities,
            quantities=self._table.capabilities.quantities,
            sign_convention=self._table.capabilities.sign_convention,
            saturation_classification=(
                self._table.capabilities.saturation_classification
            ),
            interpolation=True,
            inverse_queries=self._table.capabilities.inverse_queries,
            derivatives=self._table.capabilities.derivatives,
            metadata={
                **self._table.capabilities.metadata,
                "interpolation_backend": "staged_linear",
                "axis_order": tuple(axis.value for axis in self._policy.axes),
            },
        )

    def lookup(
        self,
        request: TechnologyLookupRequest,
    ) -> TechnologyLookupResult:
        missing = missing_capabilities(self.capabilities, request)
        if missing:
            raise TechnologyCapabilityError(
                f"interpolating backend lacks capabilities: {sorted(missing)!r}"
            )

        point, steps = interpolate_request(
            self._table,
            request,
            policy=self._policy,
        )
        source_keys = tuple(
            (
                step.axis.value,
                step.lower,
                step.upper,
                step.alpha,
            )
            for step in steps
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
                "lookup_method": (
                    "exact_table_match"
                    if not steps
                    else "staged_linear_interpolation"
                ),
                "axis_order": tuple(
                    axis.value for axis in self._policy.axes
                ),
                "interpolation_steps": len(steps),
                "source_point_count": 1 if not steps else len(steps) * 2,
                "source_keys": source_keys,
            },
            metadata=point.metadata,
        )
        return validate_lookup_result(result)


assert isinstance(InterpolatingTableTechnologyBackend, type)
