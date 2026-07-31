"""Persist a run plan, execute it, and link its resulting session artifact."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cycle import OptimizationCycleResult
from .plan_executor import (
    OptimizationRunPlanExecutor,
    RunPlanExecutionRequest,
)
from .run_plan import OptimizationRunPlan
from .run_plan_persistence import (
    OptimizationRunPlanArtifacts,
    OptimizationRunPlanPersistence,
)


class PersistedRunPlanExecutionError(RuntimeError):
    """Raised when persisted plan execution cannot complete its artifact chain."""


@dataclass(frozen=True)
class PersistedRunPlanExecutionResult:
    """Result of pre-persisting and executing one optimization run plan."""

    cycle_result: OptimizationCycleResult
    run_plan_artifacts: OptimizationRunPlanArtifacts
    session_artifact_path: Path | None

    @property
    def run_plan_json(self) -> Path:
        return self.run_plan_artifacts.run_plan_json


class PersistedOptimizationRunPlanExecutor:
    """Application boundary for auditable run-plan execution.

    Ordering is intentionally fixed:

    1. persist the selected run plan;
    2. execute the plan;
    3. identify the session artifact produced by cycle persistence;
    4. link that artifact into the run-plan document.
    """

    DEFAULT_PLAN_SUBDIRECTORY = "plan"

    def __init__(
        self,
        *,
        executor: OptimizationRunPlanExecutor,
        persistence: OptimizationRunPlanPersistence | None = None,
        plan_subdirectory: str = DEFAULT_PLAN_SUBDIRECTORY,
        require_session_artifact: bool = False,
    ) -> None:
        if not plan_subdirectory:
            raise ValueError("plan_subdirectory must not be empty")

        self.executor = executor
        self.persistence = (
            persistence or OptimizationRunPlanPersistence()
        )
        self.plan_subdirectory = plan_subdirectory
        self.require_session_artifact = bool(
            require_session_artifact
        )

    def execute(
        self,
        *,
        plan: OptimizationRunPlan,
        request: RunPlanExecutionRequest,
    ) -> PersistedRunPlanExecutionResult:
        output_directory = request.output_directory
        if output_directory is None:
            raise PersistedRunPlanExecutionError(
                "persisted run-plan execution requires an output directory"
            )

        plan_directory = (
            Path(output_directory) / self.plan_subdirectory
        )
        artifacts = self.persistence.persist(
            plan,
            plan_directory,
        )

        cycle_result = self.executor.execute(
            plan=plan,
            request=request,
        )

        session_artifact_path = self._session_artifact_path(
            cycle_result
        )
        if session_artifact_path is not None:
            self.persistence.link_session_artifact(
                artifacts.run_plan_json,
                session_artifact_path,
            )
        elif self.require_session_artifact:
            raise PersistedRunPlanExecutionError(
                "optimization cycle did not expose a session artifact path"
            )

        return PersistedRunPlanExecutionResult(
            cycle_result=cycle_result,
            run_plan_artifacts=artifacts,
            session_artifact_path=session_artifact_path,
        )

    @staticmethod
    def _session_artifact_path(
        cycle_result: OptimizationCycleResult,
    ) -> Path | None:
        """Resolve the session path without coupling to one artifact DTO name."""

        artifact_container = getattr(
            cycle_result,
            "artifacts",
            None,
        )
        if artifact_container is None:
            artifact_container = getattr(
                cycle_result,
                "persistence",
                None,
            )

        candidates: tuple[Any, ...] = (
            getattr(
                artifact_container,
                "session_artifact_path",
                None,
            ),
            getattr(
                artifact_container,
                "session_json",
                None,
            ),
            getattr(
                artifact_container,
                "session_path",
                None,
            ),
            getattr(
                cycle_result,
                "session_artifact_path",
                None,
            ),
        )

        for value in candidates:
            if value is not None:
                return Path(value)
        return None
