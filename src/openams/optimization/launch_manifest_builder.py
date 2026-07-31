"""Build launch manifests from persisted run-plan execution results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .launch_manifest import (
    OptimizationLaunchArtifacts,
    OptimizationLaunchManifest,
    OptimizationLaunchStatus,
)
from .persisted_plan_executor import (
    PersistedRunPlanExecutionResult,
)
from .run_plan import OptimizationRunPlan


@dataclass(frozen=True)
class OptimizationLaunchManifestBuilder:
    """Collect top-level artifact links without duplicating artifact content."""

    def completed(
        self,
        *,
        launch_id: str,
        plan: OptimizationRunPlan,
        execution: PersistedRunPlanExecutionResult,
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizationLaunchManifest:
        cycle_result = execution.cycle_result
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

        return OptimizationLaunchManifest(
            launch_id=launch_id,
            status=OptimizationLaunchStatus.COMPLETED,
            route=plan.route.value,
            reason_code=plan.reason_code,
            artifacts=OptimizationLaunchArtifacts(
                run_plan=execution.run_plan_json,
                session=execution.session_artifact_path,
                evaluation=self._path_from(
                    artifact_container,
                    (
                        "evaluation_artifact_path",
                        "evaluation_json",
                        "evaluation_path",
                    ),
                ),
                workflow=self._path_from(
                    artifact_container,
                    (
                        "workflow_artifact_path",
                        "workflow_result_json",
                        "workflow_path",
                    ),
                ),
            ),
            metadata=dict(metadata or {}),
        )

    def failed(
        self,
        *,
        launch_id: str,
        plan: OptimizationRunPlan,
        run_plan_path: str | Path,
        error: Exception | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OptimizationLaunchManifest:
        return OptimizationLaunchManifest(
            launch_id=launch_id,
            status=OptimizationLaunchStatus.FAILED,
            route=plan.route.value,
            reason_code=plan.reason_code,
            error=str(error),
            artifacts=OptimizationLaunchArtifacts(
                run_plan=Path(run_plan_path),
            ),
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _path_from(
        container: Any,
        names: tuple[str, ...],
    ) -> Path | None:
        if container is None:
            return None
        for name in names:
            value = getattr(container, name, None)
            if value is not None:
                return Path(value)
        return None
