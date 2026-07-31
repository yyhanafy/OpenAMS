"""Concrete adapters for the optimization-cycle orchestration ports.

These adapters translate existing OpenAMS workflow, evaluation, and persistence
interfaces into the narrow protocols required by ``OptimizationCycleOrchestrator``.
They intentionally avoid changing the behavior of the wrapped implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .evaluation import (
    CandidateEvaluationEngine,
    CandidateEvaluationSummary,
    ObjectiveDefinition,
)
from .persistence import CandidateEvaluationPersistence
from .session import CandidateProposal, OptimizationSessionState
from .session_persistence import OptimizationSessionPersistence


class AdapterConfigurationError(RuntimeError):
    """Raised when an adapter cannot satisfy its wrapped interface."""


class WorkflowCallable(Protocol):
    """Callable workflow boundary used by ``WorkflowBatchExecutorAdapter``."""

    def __call__(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        ...


@dataclass(frozen=True)
class WorkflowBatchExecutorAdapter:
    """Adapt an existing proposal-to-workflow callable to batch execution."""

    workflow: WorkflowCallable

    def execute(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        return self.workflow(tuple(proposals))


@dataclass(frozen=True)
class CandidateEvaluationEngineAdapter:
    """Adapt ``CandidateEvaluationEngine`` to the cycle evaluator protocol.

    ``screening_results_getter`` extracts the screening-result collection from
    the workflow result returned by the batch executor.
    """

    engine: CandidateEvaluationEngine
    objectives: tuple[ObjectiveDefinition, ...]
    screening_results_getter: Callable[[Any], Sequence[Any]]

    def __init__(
        self,
        *,
        engine: CandidateEvaluationEngine,
        objectives: Sequence[ObjectiveDefinition],
        screening_results_getter: Callable[[Any], Sequence[Any]],
    ) -> None:
        object.__setattr__(self, "engine", engine)
        object.__setattr__(self, "objectives", tuple(objectives))
        object.__setattr__(
            self,
            "screening_results_getter",
            screening_results_getter,
        )

    def evaluate(
        self,
        execution_result: Any,
    ) -> CandidateEvaluationSummary:
        screening_results = tuple(
            self.screening_results_getter(execution_result)
        )
        return self.engine.evaluate_many(
            screening_results,
            objectives=self.objectives,
        )


@dataclass(frozen=True)
class WorkflowPersistenceAdapter:
    """Adapt an existing workflow persistence object to the cycle port.

    The wrapped object must expose::

        persist(workflow_result, output_directory)

    and the returned artifact bundle must expose ``workflow_result_json``.
    """

    persistence: Any
    subdirectory: str = "workflow"

    def persist_workflow(
        self,
        execution_result: Any,
        output_directory: Path,
    ) -> Path | None:
        directory = output_directory / self.subdirectory
        artifacts = self.persistence.persist(
            execution_result,
            directory,
        )
        path = getattr(artifacts, "workflow_result_json", None)
        if path is None:
            raise AdapterConfigurationError(
                "workflow persistence result does not expose "
                "'workflow_result_json'"
            )
        return Path(path)


@dataclass(frozen=True)
class CandidateEvaluationPersistenceAdapter:
    """Adapt ``CandidateEvaluationPersistence`` to the cycle port."""

    persistence: CandidateEvaluationPersistence
    subdirectory: str = "evaluation"

    def persist_evaluation(
        self,
        summary: CandidateEvaluationSummary,
        output_directory: Path,
        *,
        workflow_artifact_path: Path | None,
    ) -> Path | None:
        directory = output_directory / self.subdirectory
        artifacts = self.persistence.persist(
            summary,
            directory,
            workflow_result_path=workflow_artifact_path,
        )
        return Path(artifacts.evaluation_json)


@dataclass(frozen=True)
class OptimizationSessionPersistenceAdapter:
    """Adapt ``OptimizationSessionPersistence`` to the cycle port."""

    persistence: OptimizationSessionPersistence
    subdirectory: str = "session"

    def persist_session(
        self,
        state: OptimizationSessionState,
        output_directory: Path,
        *,
        evaluation_artifact_path: Path | None,
    ) -> Path | None:
        directory = output_directory / self.subdirectory
        artifacts = self.persistence.persist(
            state,
            directory,
            evaluation_artifact_path=evaluation_artifact_path,
        )
        return Path(artifacts.session_json)


@dataclass(frozen=True)
class ProposalAssignmentMapper:
    """Convert candidate proposals into assignment dictionaries.

    This is a minimal translation boundary for existing fixed-assignment
    simulation workflows that consume mappings instead of proposal objects.
    """

    include_candidate_id: bool = True
    candidate_id_field: str = "candidate_id"

    def map(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> tuple[dict[str, Any], ...]:
        assignments = []
        for proposal in proposals:
            assignment: dict[str, Any] = {
                str(name): float(value)
                for name, value in sorted(proposal.parameters.items())
            }
            if self.include_candidate_id:
                assignment[self.candidate_id_field] = proposal.candidate_id
            assignments.append(assignment)
        return tuple(assignments)


@dataclass(frozen=True)
class AssignmentWorkflowExecutorAdapter:
    """Adapt an assignment-oriented workflow to proposal batch execution.

    The wrapped callable receives a tuple of assignment mappings generated by
    ``ProposalAssignmentMapper``.
    """

    workflow: Callable[[Sequence[Mapping[str, Any]]], Any]
    mapper: ProposalAssignmentMapper = ProposalAssignmentMapper()

    def execute(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        assignments = self.mapper.map(proposals)
        return self.workflow(assignments)
