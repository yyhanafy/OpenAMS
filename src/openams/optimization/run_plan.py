"""Run-plan modeling and route selection for OpenAMS optimization execution.

The selector consumes synthesis output that explicitly distinguishes resolved
assignments from unresolved parameter ranges. It does not infer independent
variables from simulator behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Sequence

from .session import OptimizationRoute


class RunPlanError(RuntimeError):
    """Base error for run-plan construction."""


class ResolutionState(str, Enum):
    """Resolution state reported by assignment synthesis."""

    FULLY_RESOLVED = "fully_resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ParameterRange:
    """Validated unresolved range for one search parameter."""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        lower = float(self.lower)
        upper = float(self.upper)

        if not math.isfinite(lower) or not math.isfinite(upper):
            raise ValueError("parameter range bounds must be finite")
        if lower > upper:
            raise ValueError("parameter range lower bound exceeds upper bound")

        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    @property
    def is_degenerate(self) -> bool:
        return self.lower == self.upper

    def to_tuple(self) -> tuple[float, float]:
        return (self.lower, self.upper)

    def to_dict(self) -> dict[str, float]:
        return {
            "lower": self.lower,
            "upper": self.upper,
        }


@dataclass(frozen=True)
class SynthesisRunInput:
    """Normalized synthesis output used for route selection."""

    assignments: tuple[Mapping[str, float], ...] = ()
    unresolved_ranges: Mapping[str, ParameterRange] = field(
        default_factory=dict
    )
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        assignments: Sequence[Mapping[str, float]] = (),
        unresolved_ranges: Mapping[
            str,
            ParameterRange | tuple[float, float],
        ] | None = None,
        fixed_parameters: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_assignments = []
        for assignment in assignments:
            normalized_assignments.append(
                {
                    str(name): float(value)
                    for name, value in sorted(assignment.items())
                }
            )

        normalized_ranges = {}
        for name, bounds in (unresolved_ranges or {}).items():
            if isinstance(bounds, ParameterRange):
                parameter_range = bounds
            else:
                parameter_range = ParameterRange(
                    lower=float(bounds[0]),
                    upper=float(bounds[1]),
                )
            normalized_ranges[str(name)] = parameter_range

        normalized_fixed = {
            str(name): float(value)
            for name, value in sorted((fixed_parameters or {}).items())
        }

        object.__setattr__(
            self,
            "assignments",
            tuple(normalized_assignments),
        )
        object.__setattr__(
            self,
            "unresolved_ranges",
            dict(sorted(normalized_ranges.items())),
        )
        object.__setattr__(
            self,
            "fixed_parameters",
            normalized_fixed,
        )
        object.__setattr__(
            self,
            "metadata",
            dict(metadata or {}),
        )

    @property
    def resolution_state(self) -> ResolutionState:
        has_assignments = bool(self.assignments)
        has_ranges = bool(self.unresolved_ranges)

        if has_assignments and not has_ranges:
            return ResolutionState.FULLY_RESOLVED
        if has_ranges and (
            has_assignments or self.fixed_parameters
        ):
            return ResolutionState.PARTIALLY_RESOLVED
        return ResolutionState.UNRESOLVED


@dataclass(frozen=True)
class OptimizationRunPlan:
    """Explicit execution plan selected from synthesis output."""

    route: OptimizationRoute
    resolution_state: ResolutionState
    reason_code: str
    reason: str
    assignments: tuple[Mapping[str, float], ...] = ()
    parameter_bounds: Mapping[str, tuple[float, float]] = field(
        default_factory=dict
    )
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requires_contract(self) -> bool:
        return self.route is OptimizationRoute.CONTRACT_SEARCH

    @property
    def candidate_count(self) -> int:
        return len(self.assignments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "resolution_state": self.resolution_state.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "requires_contract": self.requires_contract,
            "candidate_count": self.candidate_count,
            "assignments": [
                dict(assignment)
                for assignment in self.assignments
            ],
            "parameter_bounds": {
                name: {
                    "lower": bounds[0],
                    "upper": bounds[1],
                }
                for name, bounds in sorted(
                    self.parameter_bounds.items()
                )
            },
            "fixed_parameters": dict(self.fixed_parameters),
            "metadata": dict(self.metadata),
        }


class OptimizationRouteSelector:
    """Select direct simulation or contract search from synthesis output."""

    DIRECT_REASON_CODE = "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    SEARCH_REASON_CODE = "UNRESOLVED_PARAMETER_RANGES_PRESENT"

    def select(
        self,
        synthesis: SynthesisRunInput,
    ) -> OptimizationRunPlan:
        if synthesis.unresolved_ranges:
            bounds = {
                name: parameter_range.to_tuple()
                for name, parameter_range in sorted(
                    synthesis.unresolved_ranges.items()
                )
            }
            unresolved_names = ", ".join(bounds)
            return OptimizationRunPlan(
                route=OptimizationRoute.CONTRACT_SEARCH,
                resolution_state=synthesis.resolution_state,
                reason_code=self.SEARCH_REASON_CODE,
                reason=(
                    "Contract search is required because synthesis left "
                    f"unresolved ranges for: {unresolved_names}."
                ),
                assignments=synthesis.assignments,
                parameter_bounds=bounds,
                fixed_parameters=synthesis.fixed_parameters,
                metadata=synthesis.metadata,
            )

        if synthesis.assignments:
            return OptimizationRunPlan(
                route=OptimizationRoute.DIRECT_SIMULATION,
                resolution_state=ResolutionState.FULLY_RESOLVED,
                reason_code=self.DIRECT_REASON_CODE,
                reason=(
                    "Direct simulation is selected because every synthesized "
                    "assignment is fully resolved and no parameter ranges "
                    "remain."
                ),
                assignments=synthesis.assignments,
                parameter_bounds={},
                fixed_parameters=synthesis.fixed_parameters,
                metadata=synthesis.metadata,
            )

        raise RunPlanError(
            "synthesis output contains neither resolved assignments nor "
            "unresolved parameter ranges"
        )
