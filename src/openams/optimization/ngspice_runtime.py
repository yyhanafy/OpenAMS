"""Concrete ngspice infrastructure leaf for optimization composition."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from openams.simulation.persistence import SimulationWorkflowPersistence

from .adapters import (
    AssignmentWorkflowExecutorAdapter,
    CandidateEvaluationEngineAdapter,
    CandidateEvaluationPersistenceAdapter,
    OptimizationSessionPersistenceAdapter,
    ProposalAssignmentMapper,
    WorkflowPersistenceAdapter,
)
from .application import (
    OptimizationApplicationService,
    OptimizationApplicationServices,
)
from .cycle import OptimizationCyclePersistence
from .evaluation import (
    CandidateEvaluationEngine,
    ObjectiveDefinition,
)
from .persistence import CandidateEvaluationPersistence
from .plan_executor import (
    OptimizationRunPlanExecutor,
    RunPlanExecutionRequest,
)
from .proposers import GridSearchProposer, MidpointProposer
from .run_plan import OptimizationRunPlan
from .session import OptimizationRoute
from .session_persistence import OptimizationSessionPersistence


class NgspiceRuntimeConfigurationError(RuntimeError):
    """Raised when the ngspice optimization leaf cannot be assembled."""


DEFAULT_NGSPICE_RUNTIME_CONFIG_ENV = (
    "OPENAMS_NGSPICE_OPTIMIZATION_CONFIG"
)


@dataclass(frozen=True)
class NgspiceRuntimeSpec:
    """Configuration for the concrete ngspice optimization leaf."""

    assignment_workflow_factory: str
    objectives_factory: str
    screening_results_getter_factory: str | None = None
    proposer: str = "grid"
    points_per_dimension: int = 3
    include_candidate_id: bool = True
    candidate_id_field: str = "candidate_id"

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "NgspiceRuntimeSpec":
        workflow_factory = cls._required_reference(
            payload,
            "assignment_workflow_factory",
        )
        objectives_factory = cls._required_reference(
            payload,
            "objectives_factory",
        )

        getter = payload.get("screening_results_getter_factory")
        if getter is not None and (
            not isinstance(getter, str) or not getter
        ):
            raise NgspiceRuntimeConfigurationError(
                "screening_results_getter_factory must be a "
                "non-empty module:function reference"
            )

        proposer = payload.get("proposer", "grid")
        if proposer not in {"grid", "midpoint"}:
            raise NgspiceRuntimeConfigurationError(
                "proposer must be 'grid' or 'midpoint'"
            )

        points = payload.get("points_per_dimension", 3)
        try:
            points = int(points)
        except (TypeError, ValueError) as exc:
            raise NgspiceRuntimeConfigurationError(
                "points_per_dimension must be an integer"
            ) from exc
        if points <= 0:
            raise NgspiceRuntimeConfigurationError(
                "points_per_dimension must be positive"
            )

        include_id = payload.get("include_candidate_id", True)
        if not isinstance(include_id, bool):
            raise NgspiceRuntimeConfigurationError(
                "include_candidate_id must be a boolean"
            )

        id_field = payload.get(
            "candidate_id_field",
            "candidate_id",
        )
        if not isinstance(id_field, str) or not id_field:
            raise NgspiceRuntimeConfigurationError(
                "candidate_id_field must be a non-empty string"
            )

        return cls(
            assignment_workflow_factory=workflow_factory,
            objectives_factory=objectives_factory,
            screening_results_getter_factory=getter,
            proposer=proposer,
            points_per_dimension=points,
            include_candidate_id=include_id,
            candidate_id_field=id_field,
        )

    @staticmethod
    def _required_reference(
        payload: Mapping[str, Any],
        name: str,
    ) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise NgspiceRuntimeConfigurationError(
                f"{name} must be a non-empty module:function reference"
            )
        return value


class ReferenceProposerRunPlanExecutor(
    OptimizationRunPlanExecutor
):
    """Inject the configured reference proposer for contract search."""

    def __init__(
        self,
        application: OptimizationApplicationService,
        *,
        contract_proposer: Any,
    ) -> None:
        super().__init__(application)
        self.contract_proposer = contract_proposer

    def execute(
        self,
        *,
        plan: OptimizationRunPlan,
        request: RunPlanExecutionRequest,
    ):
        if (
            plan.route is OptimizationRoute.CONTRACT_SEARCH
            and request.proposer is None
        ):
            request = RunPlanExecutionRequest(
                session_id=request.session_id,
                output_directory=request.output_directory,
                proposer=self.contract_proposer,
                session=request.session,
                batch_size=request.batch_size,
                session_metadata=request.session_metadata,
                iteration_metadata=request.iteration_metadata,
            )
        return super().execute(plan=plan, request=request)


class NgspiceOptimizationRuntimeFactory:
    """Build the concrete repository ngspice run-plan executor."""

    def build(
        self,
        spec: NgspiceRuntimeSpec,
    ) -> OptimizationRunPlanExecutor:
        workflow = self._load_callable_result(
            spec.assignment_workflow_factory
        )
        if not callable(workflow):
            raise NgspiceRuntimeConfigurationError(
                "assignment workflow factory must return a callable"
            )

        objectives = tuple(
            self._load_callable_result(spec.objectives_factory)
        )
        if not objectives:
            raise NgspiceRuntimeConfigurationError(
                "objectives factory returned no objectives"
            )
        if not all(
            isinstance(item, ObjectiveDefinition)
            for item in objectives
        ):
            raise NgspiceRuntimeConfigurationError(
                "objectives factory must return ObjectiveDefinition objects"
            )

        if spec.screening_results_getter_factory:
            getter = self._load_callable_result(
                spec.screening_results_getter_factory
            )
            if not callable(getter):
                raise NgspiceRuntimeConfigurationError(
                    "screening-results getter factory must "
                    "return a callable"
                )
        else:
            getter = self._default_screening_results_getter

        mapper = ProposalAssignmentMapper(
            include_candidate_id=spec.include_candidate_id,
            candidate_id_field=spec.candidate_id_field,
        )
        executor = AssignmentWorkflowExecutorAdapter(
            workflow=workflow,
            mapper=mapper,
        )

        engine = CandidateEvaluationEngine(objectives)
        evaluator = CandidateEvaluationEngineAdapter(
            engine=engine,
            screening_results_getter=getter,
        )

        persistence = OptimizationCyclePersistence(
            workflow=WorkflowPersistenceAdapter(
                SimulationWorkflowPersistence()
            ),
            evaluation=CandidateEvaluationPersistenceAdapter(
                CandidateEvaluationPersistence()
            ),
            session=OptimizationSessionPersistenceAdapter(
                OptimizationSessionPersistence()
            ),
        )

        application = OptimizationApplicationService(
            OptimizationApplicationServices(
                executor=executor,
                evaluator=evaluator,
                persistence=persistence,
            )
        )

        proposer = (
            MidpointProposer()
            if spec.proposer == "midpoint"
            else GridSearchProposer(
                points_per_dimension=spec.points_per_dimension
            )
        )
        return ReferenceProposerRunPlanExecutor(
            application,
            contract_proposer=proposer,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
    ) -> OptimizationRunPlanExecutor:
        config_path = Path(path)
        try:
            payload = json.loads(
                config_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise NgspiceRuntimeConfigurationError(
                f"failed to read ngspice runtime config: "
                f"{config_path}"
            ) from exc

        if payload.get("schema_version") != 1:
            raise NgspiceRuntimeConfigurationError(
                "unsupported ngspice runtime schema_version: "
                f"{payload.get('schema_version')!r}"
            )
        runtime = payload.get("ngspice_optimization")
        if not isinstance(runtime, Mapping):
            raise NgspiceRuntimeConfigurationError(
                "config is missing an ngspice_optimization object"
            )

        return cls().build(
            NgspiceRuntimeSpec.from_mapping(runtime)
        )

    @staticmethod
    def _default_screening_results_getter(
        workflow_result: Any,
    ) -> Sequence[Any]:
        summary = getattr(
            workflow_result,
            "screening_summary",
            None,
        )
        cases = getattr(summary, "cases", None)
        if cases is None:
            raise NgspiceRuntimeConfigurationError(
                "workflow result does not expose "
                "screening_summary.cases"
            )
        return tuple(cases)

    @staticmethod
    def _load_callable_result(reference: str) -> Any:
        factory = NgspiceOptimizationRuntimeFactory._load_callable(
            reference
        )
        return factory()

    @staticmethod
    def _load_callable(reference: str) -> Callable[[], Any]:
        if ":" not in reference:
            raise NgspiceRuntimeConfigurationError(
                "factory reference must use module:function syntax"
            )
        module_name, function_name = reference.split(":", 1)
        if not module_name or not function_name:
            raise NgspiceRuntimeConfigurationError(
                "factory reference must use module:function syntax"
            )
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise NgspiceRuntimeConfigurationError(
                f"failed to import runtime module: {module_name}"
            ) from exc
        factory = getattr(module, function_name, None)
        if not callable(factory):
            raise NgspiceRuntimeConfigurationError(
                f"factory is not callable: {reference}"
            )
        return factory


def create_run_plan_executor(
    config_path: str | Path | None = None,
) -> OptimizationRunPlanExecutor:
    """Composition-root leaf factory for the current ngspice workflow."""

    resolved = config_path
    if resolved is None:
        resolved = os.environ.get(
            DEFAULT_NGSPICE_RUNTIME_CONFIG_ENV
        )
    if resolved is None or str(resolved) == "":
        raise NgspiceRuntimeConfigurationError(
            "ngspice optimization config is required; pass "
            "config_path or set "
            f"{DEFAULT_NGSPICE_RUNTIME_CONFIG_ENV}"
        )
    return NgspiceOptimizationRuntimeFactory.from_file(resolved)
