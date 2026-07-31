"""End-to-end optimizer-neutral optimization-cycle orchestration.

The orchestrator coordinates proposal generation, candidate execution,
evaluation, feedback application, and optional persistence without owning
simulator-, topology-, or optimizer-specific logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .evaluation import CandidateEvaluationSummary, OptimizerFeedback
from .session import (
    CandidateProposal,
    CandidateProposer,
    OptimizationRoute,
    OptimizationSession,
    OptimizationSessionState,
    ProposalRequest,
)


class OptimizationCycleError(RuntimeError):
    """Base error for optimization-cycle orchestration."""


class CandidateBatchExecutor(Protocol):
    """Execute one batch of proposed candidates.

    A concrete implementation may render SPICE decks, invoke ngspice, parse
    raw results, and run specification screening.
    """

    def execute(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        ...


class CandidateBatchEvaluator(Protocol):
    """Convert execution output into candidate evaluations."""

    def evaluate(
        self,
        execution_result: Any,
    ) -> CandidateEvaluationSummary:
        ...


class WorkflowArtifactPersister(Protocol):
    """Persist execution/workflow artifacts and return their primary path."""

    def persist_workflow(
        self,
        execution_result: Any,
        output_directory: Path,
    ) -> Path | None:
        ...


class EvaluationArtifactPersister(Protocol):
    """Persist evaluation artifacts and return their primary path."""

    def persist_evaluation(
        self,
        summary: CandidateEvaluationSummary,
        output_directory: Path,
        *,
        workflow_artifact_path: Path | None,
    ) -> Path | None:
        ...


class SessionArtifactPersister(Protocol):
    """Persist optimization-session artifacts and return their primary path."""

    def persist_session(
        self,
        state: OptimizationSessionState,
        output_directory: Path,
        *,
        evaluation_artifact_path: Path | None,
    ) -> Path | None:
        ...


@dataclass(frozen=True)
class OptimizationCycleArtifacts:
    """Primary artifact links emitted by one completed cycle."""

    workflow_artifact_path: Path | None = None
    evaluation_artifact_path: Path | None = None
    session_artifact_path: Path | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "workflow_artifact_path": (
                None
                if self.workflow_artifact_path is None
                else str(self.workflow_artifact_path)
            ),
            "evaluation_artifact_path": (
                None
                if self.evaluation_artifact_path is None
                else str(self.evaluation_artifact_path)
            ),
            "session_artifact_path": (
                None
                if self.session_artifact_path is None
                else str(self.session_artifact_path)
            ),
        }


@dataclass(frozen=True)
class OptimizationCycleResult:
    """Complete result for one optimization iteration."""

    iteration_index: int
    route: OptimizationRoute
    proposals: tuple[CandidateProposal, ...]
    execution_result: Any
    evaluation_summary: CandidateEvaluationSummary
    feedback: tuple[OptimizerFeedback, ...]
    session_state: OptimizationSessionState
    artifacts: OptimizationCycleArtifacts = field(
        default_factory=OptimizationCycleArtifacts
    )

    @property
    def candidate_count(self) -> int:
        return len(self.proposals)

    @property
    def valid_count(self) -> int:
        return sum(item.feasible is True for item in self.feedback)

    @property
    def infeasible_count(self) -> int:
        return sum(item.feasible is False for item in self.feedback)

    @property
    def unknown_count(self) -> int:
        return sum(item.feasible is None for item in self.feedback)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration_index": self.iteration_index,
            "route": self.route.value,
            "candidate_count": self.candidate_count,
            "valid_count": self.valid_count,
            "infeasible_count": self.infeasible_count,
            "unknown_count": self.unknown_count,
            "proposals": [item.to_dict() for item in self.proposals],
            "feedback": [item.to_dict() for item in self.feedback],
            "session": self.session_state.to_dict(),
            "artifacts": self.artifacts.to_dict(),
        }


@dataclass(frozen=True)
class OptimizationCyclePersistence:
    """Optional persistence services used by the orchestrator."""

    workflow: WorkflowArtifactPersister | None = None
    evaluation: EvaluationArtifactPersister | None = None
    session: SessionArtifactPersister | None = None


class OptimizationCycleOrchestrator:
    """Run one complete proposal-to-feedback optimization cycle."""

    def __init__(
        self,
        *,
        executor: CandidateBatchExecutor,
        evaluator: CandidateBatchEvaluator,
        persistence: OptimizationCyclePersistence | None = None,
    ) -> None:
        self.executor = executor
        self.evaluator = evaluator
        self.persistence = persistence or OptimizationCyclePersistence()

    @staticmethod
    def _feedback_from_summary(
        summary: CandidateEvaluationSummary,
    ) -> tuple[OptimizerFeedback, ...]:
        feedback = tuple(
            evaluation.optimizer_feedback()
            for evaluation in sorted(
                summary.evaluations,
                key=lambda item: item.candidate_id,
            )
        )

        identifiers = [item.candidate_id for item in feedback]
        if len(set(identifiers)) != len(identifiers):
            raise OptimizationCycleError(
                "evaluation summary produced duplicate candidate identifiers"
            )

        return feedback

    @staticmethod
    def _validate_candidate_coverage(
        proposals: Sequence[CandidateProposal],
        feedback: Sequence[OptimizerFeedback],
    ) -> None:
        proposed_ids = {
            proposal.candidate_id
            for proposal in proposals
        }
        feedback_ids = {
            item.candidate_id
            for item in feedback
        }

        missing = sorted(proposed_ids - feedback_ids)
        unexpected = sorted(feedback_ids - proposed_ids)

        if missing or unexpected:
            details = []
            if missing:
                details.append(
                    "missing feedback for: " + ", ".join(missing)
                )
            if unexpected:
                details.append(
                    "unexpected feedback for: " + ", ".join(unexpected)
                )
            raise OptimizationCycleError("; ".join(details))

    def run(
        self,
        *,
        session: OptimizationSession,
        proposer: CandidateProposer,
        request: ProposalRequest,
        output_directory: str | Path | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizationCycleResult:
        if request.session != session.state:
            raise OptimizationCycleError(
                "proposal request session does not match current session state"
            )

        iteration_index = session.state.next_iteration_index
        proposals = tuple(proposer.propose(request))

        if len(proposals) != request.batch_size:
            raise OptimizationCycleError(
                f"proposer returned {len(proposals)} candidates; "
                f"expected {request.batch_size}"
            )

        session.record_proposals(
            proposals,
            metadata=dict(metadata or {}),
        )

        execution_result = self.executor.execute(proposals)
        evaluation_summary = self.evaluator.evaluate(execution_result)
        feedback = self._feedback_from_summary(evaluation_summary)
        self._validate_candidate_coverage(proposals, feedback)

        session.apply_feedback(iteration_index, feedback)

        artifacts = OptimizationCycleArtifacts()
        if output_directory is not None:
            directory = Path(output_directory)
            directory.mkdir(parents=True, exist_ok=True)

            workflow_path = None
            if self.persistence.workflow is not None:
                workflow_path = self.persistence.workflow.persist_workflow(
                    execution_result,
                    directory,
                )

            evaluation_path = None
            if self.persistence.evaluation is not None:
                evaluation_path = (
                    self.persistence.evaluation.persist_evaluation(
                        evaluation_summary,
                        directory,
                        workflow_artifact_path=workflow_path,
                    )
                )

            session_path = None
            if self.persistence.session is not None:
                session_path = self.persistence.session.persist_session(
                    session.state,
                    directory,
                    evaluation_artifact_path=evaluation_path,
                )

            artifacts = OptimizationCycleArtifacts(
                workflow_artifact_path=workflow_path,
                evaluation_artifact_path=evaluation_path,
                session_artifact_path=session_path,
            )

        return OptimizationCycleResult(
            iteration_index=iteration_index,
            route=session.state.route,
            proposals=proposals,
            execution_result=execution_result,
            evaluation_summary=evaluation_summary,
            feedback=feedback,
            session_state=session.state,
            artifacts=artifacts,
        )
