"""Deterministic reference candidate proposers.

These proposers provide reproducible baseline implementations for:
- fully resolved direct-simulation assignments;
- bounded contract-search candidate generation.

They intentionally avoid optimizer-specific model state.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any, Iterable, Mapping, Sequence

from .session import (
    CandidateProposal,
    OptimizationRoute,
    ProposalRequest,
)


class ProposalGenerationError(RuntimeError):
    """Base error for deterministic proposal generation."""


def _candidate_id(
    *,
    session_id: str,
    iteration: int,
    proposal_index: int,
) -> str:
    safe_session = "".join(
        character if character.isalnum() or character in ("-", "_") else "_"
        for character in session_id
    )
    return (
        f"{safe_session}_"
        f"iter_{iteration:04d}_"
        f"candidate_{proposal_index:04d}"
    )


def _sorted_float_mapping(
    values: Mapping[str, float],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, value in sorted(values.items()):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ProposalGenerationError(
                f"parameter {name!r} must be finite"
            )
        result[str(name)] = numeric
    return result


@dataclass(frozen=True)
class DirectAssignmentProposer:
    """Emit fully resolved assignments for direct simulation."""

    assignments: tuple[Mapping[str, float], ...]
    source: str = "direct_assignment_reference"

    def __init__(
        self,
        assignments: Iterable[Mapping[str, float]],
        *,
        source: str = "direct_assignment_reference",
    ) -> None:
        object.__setattr__(self, "assignments", tuple(assignments))
        object.__setattr__(self, "source", source)

        if not self.assignments:
            raise ValueError("at least one direct assignment is required")

    def propose(
        self,
        request: ProposalRequest,
    ) -> Sequence[CandidateProposal]:
        if request.session.route is not OptimizationRoute.DIRECT_SIMULATION:
            raise ProposalGenerationError(
                "DirectAssignmentProposer requires direct_simulation route"
            )
        if request.parameter_bounds:
            raise ProposalGenerationError(
                "direct assignments cannot contain unresolved ranges"
            )
        if request.batch_size > len(self.assignments):
            raise ProposalGenerationError(
                f"requested {request.batch_size} assignments, "
                f"but only {len(self.assignments)} are available"
            )

        proposals = []
        for index, assignment in enumerate(
            self.assignments[: request.batch_size]
        ):
            overlap = set(assignment) & set(request.fixed_parameters)
            inconsistent = sorted(
                name
                for name in overlap
                if float(assignment[name])
                != float(request.fixed_parameters[name])
            )
            if inconsistent:
                raise ProposalGenerationError(
                    "direct assignment conflicts with fixed parameters: "
                    + ", ".join(inconsistent)
                )

            parameters = {
                **_sorted_float_mapping(request.fixed_parameters),
                **_sorted_float_mapping(assignment),
            }
            proposals.append(
                CandidateProposal(
                    candidate_id=_candidate_id(
                        session_id=request.session.session_id,
                        iteration=request.session.next_iteration_index,
                        proposal_index=index,
                    ),
                    parameters=parameters,
                    route=OptimizationRoute.DIRECT_SIMULATION,
                    iteration=request.session.next_iteration_index,
                    proposal_index=index,
                    source=self.source,
                    metadata={
                        "reference_proposer": "direct_assignment",
                    },
                )
            )

        return tuple(proposals)


@dataclass(frozen=True)
class GridSearchProposer:
    """Generate deterministic bounded contract-search candidates."""

    points_per_dimension: int = 3
    source: str = "grid_search_reference"

    def __post_init__(self) -> None:
        if self.points_per_dimension <= 0:
            raise ValueError("points_per_dimension must be positive")

    @staticmethod
    def _axis(
        lower: float,
        upper: float,
        count: int,
    ) -> tuple[float, ...]:
        if count == 1 or lower == upper:
            return ((lower + upper) / 2.0,)
        step = (upper - lower) / float(count - 1)
        return tuple(lower + step * index for index in range(count))

    def propose(
        self,
        request: ProposalRequest,
    ) -> Sequence[CandidateProposal]:
        if request.session.route is not OptimizationRoute.CONTRACT_SEARCH:
            raise ProposalGenerationError(
                "GridSearchProposer requires contract_search route"
            )
        if not request.parameter_bounds:
            raise ProposalGenerationError(
                "grid search requires unresolved parameter bounds"
            )

        names = tuple(sorted(request.parameter_bounds))
        axes = tuple(
            self._axis(
                float(request.parameter_bounds[name][0]),
                float(request.parameter_bounds[name][1]),
                self.points_per_dimension,
            )
            for name in names
        )
        combinations = itertools.product(*axes)

        proposals = []
        for index, values in enumerate(combinations):
            if index >= request.batch_size:
                break

            parameters = {
                **_sorted_float_mapping(request.fixed_parameters),
                **{
                    name: float(value)
                    for name, value in zip(names, values, strict=True)
                },
            }
            proposals.append(
                CandidateProposal(
                    candidate_id=_candidate_id(
                        session_id=request.session.session_id,
                        iteration=request.session.next_iteration_index,
                        proposal_index=index,
                    ),
                    parameters=parameters,
                    route=OptimizationRoute.CONTRACT_SEARCH,
                    iteration=request.session.next_iteration_index,
                    proposal_index=index,
                    source=self.source,
                    metadata={
                        "reference_proposer": "grid_search",
                        "points_per_dimension": self.points_per_dimension,
                    },
                )
            )

        if len(proposals) < request.batch_size:
            raise ProposalGenerationError(
                f"grid contains only {len(proposals)} unique candidates, "
                f"but batch_size is {request.batch_size}"
            )

        return tuple(proposals)


@dataclass(frozen=True)
class MidpointProposer:
    """Emit one deterministic midpoint candidate for contract search."""

    source: str = "midpoint_reference"

    def propose(
        self,
        request: ProposalRequest,
    ) -> Sequence[CandidateProposal]:
        if request.session.route is not OptimizationRoute.CONTRACT_SEARCH:
            raise ProposalGenerationError(
                "MidpointProposer requires contract_search route"
            )
        if request.batch_size != 1:
            raise ProposalGenerationError(
                "MidpointProposer supports batch_size=1 only"
            )

        parameters = _sorted_float_mapping(request.fixed_parameters)
        for name, bounds in sorted(request.parameter_bounds.items()):
            lower, upper = bounds
            parameters[name] = (float(lower) + float(upper)) / 2.0

        return (
            CandidateProposal(
                candidate_id=_candidate_id(
                    session_id=request.session.session_id,
                    iteration=request.session.next_iteration_index,
                    proposal_index=0,
                ),
                parameters=parameters,
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=request.session.next_iteration_index,
                proposal_index=0,
                source=self.source,
                metadata={
                    "reference_proposer": "midpoint",
                },
            ),
        )
