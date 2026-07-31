"""Optimizer-neutral candidate proposal and optimization-session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .evaluation import CandidateState, OptimizerFeedback


class OptimizationSessionError(RuntimeError):
    """Base error for optimization-session orchestration."""


class OptimizationRoute(str, Enum):
    DIRECT_SIMULATION = "direct_simulation"
    CONTRACT_SEARCH = "contract_search"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CandidateProposal:
    """One optimizer-neutral candidate proposal."""

    candidate_id: str
    parameters: Mapping[str, float]
    route: OptimizationRoute
    iteration: int
    proposal_index: int
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if self.iteration < 0:
            raise ValueError("iteration must be non-negative")
        if self.proposal_index < 0:
            raise ValueError("proposal_index must be non-negative")
        if not self.parameters:
            raise ValueError("candidate proposal must contain parameters")

        for name, value in self.parameters.items():
            if not str(name).strip():
                raise ValueError("parameter names must be non-empty")
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(
                    f"parameter {name!r} must be a finite scalar"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "parameters": {
                str(name): float(value)
                for name, value in sorted(self.parameters.items())
            },
            "route": self.route.value,
            "iteration": self.iteration,
            "proposal_index": self.proposal_index,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProposalRecord:
    """Proposal plus optional optimizer feedback."""

    proposal: CandidateProposal
    status: ProposalStatus
    feedback: OptimizerFeedback | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if self.status is ProposalStatus.EVALUATED and self.feedback is None:
            raise ValueError("evaluated proposal requires feedback")
        if self.feedback is not None:
            if self.feedback.candidate_id != self.proposal.candidate_id:
                raise ValueError(
                    "feedback candidate_id does not match proposal candidate_id"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "status": self.status.value,
            "feedback": (
                None if self.feedback is None else self.feedback.to_dict()
            ),
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class OptimizationIteration:
    """Immutable record for one proposal/evaluation iteration."""

    index: int
    records: tuple[ProposalRecord, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("iteration index must be non-negative")
        for record in self.records:
            if record.proposal.iteration != self.index:
                raise ValueError(
                    "proposal iteration does not match iteration record"
                )

    @property
    def proposed_count(self) -> int:
        return len(self.records)

    @property
    def evaluated_count(self) -> int:
        return sum(
            record.status is ProposalStatus.EVALUATED
            for record in self.records
        )

    @property
    def valid_count(self) -> int:
        return sum(
            record.feedback is not None
            and record.feedback.state is CandidateState.VALID
            for record in self.records
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "proposed_count": self.proposed_count,
            "evaluated_count": self.evaluated_count,
            "valid_count": self.valid_count,
            "records": [record.to_dict() for record in self.records],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OptimizationSessionState:
    """Complete immutable optimization-session history."""

    session_id: str
    route: OptimizationRoute
    iterations: tuple[OptimizationIteration, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty")

        expected = list(range(len(self.iterations)))
        actual = [iteration.index for iteration in self.iterations]
        if actual != expected:
            raise ValueError(
                "iteration indices must be contiguous and start at zero"
            )

        candidate_ids: list[str] = []
        for iteration in self.iterations:
            for record in iteration.records:
                if record.proposal.route is not self.route:
                    raise ValueError(
                        "proposal route does not match session route"
                    )
                candidate_ids.append(record.proposal.candidate_id)

        duplicates = sorted(
            {
                candidate_id
                for candidate_id in candidate_ids
                if candidate_ids.count(candidate_id) > 1
            }
        )
        if duplicates:
            raise ValueError(
                "duplicate candidate identifiers in session: "
                + ", ".join(duplicates)
            )

    @property
    def next_iteration_index(self) -> int:
        return len(self.iterations)

    @property
    def candidate_count(self) -> int:
        return sum(
            len(iteration.records)
            for iteration in self.iterations
        )

    @property
    def evaluated_count(self) -> int:
        return sum(
            iteration.evaluated_count
            for iteration in self.iterations
        )

    @property
    def valid_count(self) -> int:
        return sum(iteration.valid_count for iteration in self.iterations)

    def with_iteration(
        self,
        iteration: OptimizationIteration,
    ) -> "OptimizationSessionState":
        if iteration.index != self.next_iteration_index:
            raise OptimizationSessionError(
                f"expected iteration {self.next_iteration_index}, "
                f"received {iteration.index}"
            )
        return OptimizationSessionState(
            session_id=self.session_id,
            route=self.route,
            iterations=(*self.iterations, iteration),
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "route": self.route.value,
            "iteration_count": len(self.iterations),
            "candidate_count": self.candidate_count,
            "evaluated_count": self.evaluated_count,
            "valid_count": self.valid_count,
            "iterations": [
                iteration.to_dict()
                for iteration in self.iterations
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProposalRequest:
    """Optimizer-neutral request for a new candidate batch."""

    session: OptimizationSessionState
    batch_size: int
    parameter_bounds: Mapping[str, tuple[float, float]]
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if (
            self.session.route is OptimizationRoute.CONTRACT_SEARCH
            and not self.parameter_bounds
        ):
            raise ValueError(
                "contract-search route requires unresolved parameter ranges"
            )

        overlap = set(self.parameter_bounds) & set(self.fixed_parameters)
        if overlap:
            raise ValueError(
                "parameters cannot be both ranged and fixed: "
                + ", ".join(sorted(overlap))
            )

        for name, bounds in self.parameter_bounds.items():
            if len(bounds) != 2:
                raise ValueError(
                    f"bounds for {name!r} must contain lower and upper"
                )
            lower, upper = bounds
            if not math.isfinite(lower) or not math.isfinite(upper):
                raise ValueError(f"bounds for {name!r} must be finite")
            if lower > upper:
                raise ValueError(
                    f"lower bound exceeds upper bound for {name!r}"
                )

        for name, value in self.fixed_parameters.items():
            if not math.isfinite(value):
                raise ValueError(
                    f"fixed parameter {name!r} must be finite"
                )

        if (
            self.session.route is OptimizationRoute.DIRECT_SIMULATION
            and self.parameter_bounds
        ):
            raise ValueError(
                "direct-simulation route must not contain unresolved ranges"
            )


    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.to_dict(),
            "batch_size": self.batch_size,
            "parameter_bounds": {
                name: [float(bounds[0]), float(bounds[1])]
                for name, bounds in sorted(self.parameter_bounds.items())
            },
            "fixed_parameters": {
                name: float(value)
                for name, value in sorted(self.fixed_parameters.items())
            },
            "metadata": dict(self.metadata),
        }


class CandidateProposer(Protocol):
    """Protocol implemented by any optimizer or deterministic proposer."""

    def propose(
        self,
        request: ProposalRequest,
    ) -> Sequence[CandidateProposal]:
        ...


class OptimizationSession:
    """State transition service around an immutable session state."""

    def __init__(self, state: OptimizationSessionState) -> None:
        self.state = state

    def record_proposals(
        self,
        proposals: Iterable[CandidateProposal],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizationSessionState:
        items = tuple(proposals)
        expected_iteration = self.state.next_iteration_index

        if not items:
            raise OptimizationSessionError(
                "cannot record an empty proposal batch"
            )

        indices = [item.proposal_index for item in items]
        if indices != list(range(len(items))):
            raise OptimizationSessionError(
                "proposal indices must be contiguous and start at zero"
            )

        for item in items:
            if item.iteration != expected_iteration:
                raise OptimizationSessionError(
                    "proposal iteration does not match next session iteration"
                )
            if item.route is not self.state.route:
                raise OptimizationSessionError(
                    "proposal route does not match session route"
                )

        iteration = OptimizationIteration(
            index=expected_iteration,
            records=tuple(
                ProposalRecord(
                    proposal=item,
                    status=ProposalStatus.PROPOSED,
                )
                for item in items
            ),
            metadata=dict(metadata or {}),
        )
        self.state = self.state.with_iteration(iteration)
        return self.state

    def apply_feedback(
        self,
        iteration_index: int,
        feedback: Iterable[OptimizerFeedback],
    ) -> OptimizationSessionState:
        if iteration_index < 0 or iteration_index >= len(self.state.iterations):
            raise OptimizationSessionError(
                f"iteration {iteration_index} does not exist"
            )

        feedback_items = tuple(feedback)
        feedback_by_id = {
            item.candidate_id: item
            for item in feedback_items
        }
        if len(feedback_by_id) != len(feedback_items):
            raise OptimizationSessionError(
                "duplicate feedback candidate identifiers"
            )

        iterations = list(self.state.iterations)
        iteration = iterations[iteration_index]
        proposal_ids = {
            record.proposal.candidate_id
            for record in iteration.records
        }

        unknown_ids = sorted(set(feedback_by_id) - proposal_ids)
        if unknown_ids:
            raise OptimizationSessionError(
                "feedback references unknown candidates: "
                + ", ".join(unknown_ids)
            )

        updated_records = []
        for record in iteration.records:
            item = feedback_by_id.get(record.proposal.candidate_id)
            if item is None:
                updated_records.append(record)
                continue
            updated_records.append(
                ProposalRecord(
                    proposal=record.proposal,
                    status=ProposalStatus.EVALUATED,
                    feedback=item,
                    diagnostic=record.diagnostic,
                )
            )

        iterations[iteration_index] = OptimizationIteration(
            index=iteration.index,
            records=tuple(updated_records),
            metadata=iteration.metadata,
        )

        self.state = OptimizationSessionState(
            session_id=self.state.session_id,
            route=self.state.route,
            iterations=tuple(iterations),
            metadata=self.state.metadata,
        )
        return self.state

    def propose_and_record(
        self,
        proposer: CandidateProposer,
        request: ProposalRequest,
    ) -> OptimizationSessionState:
        if request.session != self.state:
            raise OptimizationSessionError(
                "proposal request session does not match current session state"
            )
        proposals = tuple(proposer.propose(request))
        if len(proposals) != request.batch_size:
            raise OptimizationSessionError(
                f"proposer returned {len(proposals)} candidates; "
                f"expected {request.batch_size}"
            )
        return self.record_proposals(proposals)
