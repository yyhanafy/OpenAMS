"""High-level application service for OpenAMS optimization execution.

This module assembles proposal generation, cycle orchestration, and persistence
behind two explicit application entry points:

- ``run_direct_assignments`` for fully resolved assignments;
- ``run_contract_search_iteration`` for unresolved bounded variables.

The service preserves the architectural rule that fully resolved assignments
bypass executable-contract search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cycle import (
    CandidateBatchEvaluator,
    CandidateBatchExecutor,
    OptimizationCycleOrchestrator,
    OptimizationCyclePersistence,
    OptimizationCycleResult,
)
from .proposers import DirectAssignmentProposer
from .session import (
    CandidateProposer,
    OptimizationRoute,
    OptimizationSession,
    OptimizationSessionState,
    ProposalRequest,
)


class OptimizationApplicationError(RuntimeError):
    """Base error for high-level optimization application operations."""


@dataclass(frozen=True)
class DirectAssignmentRunRequest:
    """Input for one direct-simulation application run."""

    session_id: str
    assignments: tuple[Mapping[str, float], ...]
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    output_directory: Path | None = None
    session_metadata: Mapping[str, Any] = field(default_factory=dict)
    iteration_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        session_id: str,
        assignments: Sequence[Mapping[str, float]],
        fixed_parameters: Mapping[str, float] | None = None,
        output_directory: str | Path | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        iteration_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "session_id", str(session_id))
        object.__setattr__(self, "assignments", tuple(assignments))
        object.__setattr__(
            self,
            "fixed_parameters",
            dict(fixed_parameters or {}),
        )
        object.__setattr__(
            self,
            "output_directory",
            None if output_directory is None else Path(output_directory),
        )
        object.__setattr__(
            self,
            "session_metadata",
            dict(session_metadata or {}),
        )
        object.__setattr__(
            self,
            "iteration_metadata",
            dict(iteration_metadata or {}),
        )

        if not self.session_id:
            raise ValueError("session_id must not be empty")
        if not self.assignments:
            raise ValueError("at least one direct assignment is required")


@dataclass(frozen=True)
class ContractSearchIterationRequest:
    """Input for one bounded contract-search application iteration."""

    session: OptimizationSession
    proposer: CandidateProposer
    parameter_bounds: Mapping[str, tuple[float, float]]
    batch_size: int
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    output_directory: Path | None = None
    iteration_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        session: OptimizationSession,
        proposer: CandidateProposer,
        parameter_bounds: Mapping[str, tuple[float, float]],
        batch_size: int,
        fixed_parameters: Mapping[str, float] | None = None,
        output_directory: str | Path | None = None,
        iteration_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "proposer", proposer)
        object.__setattr__(
            self,
            "parameter_bounds",
            {
                str(name): (float(bounds[0]), float(bounds[1]))
                for name, bounds in parameter_bounds.items()
            },
        )
        object.__setattr__(self, "batch_size", int(batch_size))
        object.__setattr__(
            self,
            "fixed_parameters",
            dict(fixed_parameters or {}),
        )
        object.__setattr__(
            self,
            "output_directory",
            None if output_directory is None else Path(output_directory),
        )
        object.__setattr__(
            self,
            "iteration_metadata",
            dict(iteration_metadata or {}),
        )

        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not self.parameter_bounds:
            raise ValueError(
                "contract search requires unresolved parameter bounds"
            )


@dataclass(frozen=True)
class OptimizationApplicationServices:
    """Dependencies shared by direct and contract-search operations."""

    executor: CandidateBatchExecutor
    evaluator: CandidateBatchEvaluator
    persistence: OptimizationCyclePersistence = field(
        default_factory=OptimizationCyclePersistence
    )

    def orchestrator(self) -> OptimizationCycleOrchestrator:
        return OptimizationCycleOrchestrator(
            executor=self.executor,
            evaluator=self.evaluator,
            persistence=self.persistence,
        )


class OptimizationApplicationService:
    """Application-level façade for OpenAMS candidate execution."""

    def __init__(
        self,
        services: OptimizationApplicationServices,
    ) -> None:
        self.services = services

    def run_direct_assignments(
        self,
        request: DirectAssignmentRunRequest,
    ) -> OptimizationCycleResult:
        """Execute fully resolved assignments without contract search."""

        state = OptimizationSessionState(
            session_id=request.session_id,
            route=OptimizationRoute.DIRECT_SIMULATION,
            metadata=dict(request.session_metadata),
        )
        session = OptimizationSession(state)
        proposer = DirectAssignmentProposer(request.assignments)

        proposal_request = ProposalRequest(
            session=state,
            batch_size=len(request.assignments),
            parameter_bounds={},
            fixed_parameters=dict(request.fixed_parameters),
        )

        return self.services.orchestrator().run(
            session=session,
            proposer=proposer,
            request=proposal_request,
            output_directory=request.output_directory,
            metadata=request.iteration_metadata,
        )

    def run_contract_search_iteration(
        self,
        request: ContractSearchIterationRequest,
    ) -> OptimizationCycleResult:
        """Execute one optimizer-driven bounded-search iteration."""

        if (
            request.session.state.route
            is not OptimizationRoute.CONTRACT_SEARCH
        ):
            raise OptimizationApplicationError(
                "contract-search iteration requires a contract_search session"
            )

        proposal_request = ProposalRequest(
            session=request.session.state,
            batch_size=request.batch_size,
            parameter_bounds=request.parameter_bounds,
            fixed_parameters=dict(request.fixed_parameters),
        )

        return self.services.orchestrator().run(
            session=request.session,
            proposer=request.proposer,
            request=proposal_request,
            output_directory=request.output_directory,
            metadata=request.iteration_metadata,
        )

    @staticmethod
    def create_contract_search_session(
        *,
        session_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizationSession:
        """Create an empty resumable contract-search session."""

        if not session_id:
            raise ValueError("session_id must not be empty")

        return OptimizationSession(
            OptimizationSessionState(
                session_id=session_id,
                route=OptimizationRoute.CONTRACT_SEARCH,
                metadata=dict(metadata or {}),
            )
        )

    @staticmethod
    def resume_contract_search_session(
        state: OptimizationSessionState,
    ) -> OptimizationSession:
        """Wrap restored typed state for the next contract-search iteration."""

        if state.route is not OptimizationRoute.CONTRACT_SEARCH:
            raise OptimizationApplicationError(
                "restored state is not a contract_search session"
            )
        return OptimizationSession(state)
