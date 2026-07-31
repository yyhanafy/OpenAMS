"""Execute explicit optimization run plans through the application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .application import (
    ContractSearchIterationRequest,
    DirectAssignmentRunRequest,
    OptimizationApplicationService,
)
from .cycle import OptimizationCycleResult
from .run_plan import OptimizationRunPlan
from .session import (
    CandidateProposer,
    OptimizationRoute,
    OptimizationSession,
)


class RunPlanExecutionError(RuntimeError):
    """Raised when an optimization run plan cannot be executed."""


@dataclass(frozen=True)
class RunPlanExecutionRequest:
    """Execution-time inputs not owned by the run plan itself."""

    session_id: str
    output_directory: Path | None = None
    proposer: CandidateProposer | None = None
    session: OptimizationSession | None = None
    batch_size: int | None = None
    session_metadata: Mapping[str, Any] | None = None
    iteration_metadata: Mapping[str, Any] | None = None

    def __init__(
        self,
        *,
        session_id: str,
        output_directory: str | Path | None = None,
        proposer: CandidateProposer | None = None,
        session: OptimizationSession | None = None,
        batch_size: int | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        iteration_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be positive")

        object.__setattr__(self, "session_id", str(session_id))
        object.__setattr__(
            self,
            "output_directory",
            None if output_directory is None else Path(output_directory),
        )
        object.__setattr__(self, "proposer", proposer)
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "batch_size", batch_size)
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


class OptimizationRunPlanExecutor:
    """Dispatch an explicit run plan to the correct application operation."""

    def __init__(
        self,
        application: OptimizationApplicationService,
    ) -> None:
        self.application = application

    @staticmethod
    def _decision_metadata(
        plan: OptimizationRunPlan,
    ) -> dict[str, Any]:
        return {
            "route": plan.route.value,
            "resolution_state": plan.resolution_state.value,
            "route_reason_code": plan.reason_code,
            "route_reason": plan.reason,
            "requires_contract": plan.requires_contract,
        }

    @staticmethod
    def _merge_metadata(
        *sources: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for source in sources:
            if source:
                merged.update(dict(source))
        return merged

    def execute(
        self,
        *,
        plan: OptimizationRunPlan,
        request: RunPlanExecutionRequest,
    ) -> OptimizationCycleResult:
        decision_metadata = self._decision_metadata(plan)

        if plan.route is OptimizationRoute.DIRECT_SIMULATION:
            if request.proposer is not None:
                raise RunPlanExecutionError(
                    "direct-simulation plans must not supply a proposer"
                )
            if request.session is not None:
                raise RunPlanExecutionError(
                    "direct-simulation plans create a new direct session"
                )
            if not plan.assignments:
                raise RunPlanExecutionError(
                    "direct-simulation plan contains no assignments"
                )

            session_metadata = self._merge_metadata(
                plan.metadata,
                request.session_metadata,
                decision_metadata,
            )
            iteration_metadata = self._merge_metadata(
                request.iteration_metadata,
                decision_metadata,
            )

            return self.application.run_direct_assignments(
                DirectAssignmentRunRequest(
                    session_id=request.session_id,
                    assignments=plan.assignments,
                    fixed_parameters=plan.fixed_parameters,
                    output_directory=request.output_directory,
                    session_metadata=session_metadata,
                    iteration_metadata=iteration_metadata,
                )
            )

        if plan.route is OptimizationRoute.CONTRACT_SEARCH:
            if request.proposer is None:
                raise RunPlanExecutionError(
                    "contract-search plan requires a candidate proposer"
                )
            if not plan.parameter_bounds:
                raise RunPlanExecutionError(
                    "contract-search plan contains no parameter bounds"
                )

            session = request.session
            if session is None:
                session_metadata = self._merge_metadata(
                    plan.metadata,
                    request.session_metadata,
                    decision_metadata,
                )
                session = self.application.create_contract_search_session(
                    session_id=request.session_id,
                    metadata=session_metadata,
                )
            else:
                if session.state.session_id != request.session_id:
                    raise RunPlanExecutionError(
                        "execution request session_id does not match "
                        "the supplied optimization session"
                    )
                if (
                    session.state.route
                    is not OptimizationRoute.CONTRACT_SEARCH
                ):
                    raise RunPlanExecutionError(
                        "supplied session is not a contract_search session"
                    )

            iteration_metadata = self._merge_metadata(
                request.iteration_metadata,
                decision_metadata,
            )
            batch_size = request.batch_size or 1

            return self.application.run_contract_search_iteration(
                ContractSearchIterationRequest(
                    session=session,
                    proposer=request.proposer,
                    parameter_bounds=plan.parameter_bounds,
                    batch_size=batch_size,
                    fixed_parameters=plan.fixed_parameters,
                    output_directory=request.output_directory,
                    iteration_metadata=iteration_metadata,
                )
            )

        raise RunPlanExecutionError(
            f"unsupported optimization route: {plan.route!r}"
        )
