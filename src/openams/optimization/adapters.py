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

    ``CandidateEvaluationEngine`` already owns its objective definitions.
    ``screening_results_getter`` extracts the screening-result collection from
    the workflow result returned by the batch executor.

    The optional ``objectives`` argument is retained for source compatibility
    with the earlier adapter API. When supplied, it must match the objectives
    already held by the engine.
    """

    engine: CandidateEvaluationEngine
    screening_results_getter: Callable[[Any], Sequence[Any]]
    objectives: tuple[ObjectiveDefinition, ...]

    def __init__(
        self,
        *,
        engine: CandidateEvaluationEngine,
        screening_results_getter: Callable[[Any], Sequence[Any]],
        objectives: Sequence[ObjectiveDefinition] | None = None,
    ) -> None:
        engine_objectives = tuple(engine.objectives)
        supplied = (
            engine_objectives
            if objectives is None
            else tuple(objectives)
        )
        if supplied != engine_objectives:
            raise AdapterConfigurationError(
                "adapter objectives must match the evaluation engine"
            )

        object.__setattr__(self, "engine", engine)
        object.__setattr__(
            self,
            "screening_results_getter",
            screening_results_getter,
        )
        object.__setattr__(self, "objectives", supplied)

    def evaluate(
        self,
        execution_result: Any,
    ) -> CandidateEvaluationSummary:
        screening_results = tuple(
            self.screening_results_getter(execution_result)
        )
        return self.engine.evaluate_many(screening_results)


@dataclass(frozen=True)
class WorkflowPersistenceAdapter:
    """Adapt workflow persistence to the optimization-cycle persistence port.

    The current repository persistence returns ``workflow_json``. The earlier
    adapter contract documented ``workflow_result_json``. Both names are
    accepted to preserve compatibility with external persistence adapters.
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
            path = getattr(artifacts, "workflow_json", None)
        if path is None:
            raise AdapterConfigurationError(
                "workflow persistence result must expose "
                "'workflow_result_json' or 'workflow_json'"
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
    """Convert candidate proposals into assignment dictionaries."""

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
    """Adapt an assignment-oriented workflow to proposal batch execution."""

    workflow: Callable[[Sequence[Mapping[str, Any]]], Any]
    mapper: ProposalAssignmentMapper = ProposalAssignmentMapper()

    def execute(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        assignments = self.mapper.map(proposals)
        return self.workflow(assignments)
