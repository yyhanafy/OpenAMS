"""Atomic top-level launch service for one OpenAMS optimization run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .launch_manifest import (
    OptimizationLaunchManifest,
    OptimizationLaunchManifestArtifacts,
    OptimizationLaunchManifestPersistence,
)
from .launch_manifest_builder import (
    OptimizationLaunchManifestBuilder,
)
from .persisted_plan_executor import (
    PersistedOptimizationRunPlanExecutor,
    PersistedRunPlanExecutionResult,
)
from .plan_executor import RunPlanExecutionRequest
from .run_plan import (
    OptimizationRouteSelector,
    OptimizationRunPlan,
    SynthesisRunInput,
)


@dataclass(frozen=True)
class OptimizationLaunchRequest:
    """Inputs required to launch one optimization execution."""

    launch_id: str
    synthesis: SynthesisRunInput
    execution: RunPlanExecutionRequest
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.launch_id:
            raise ValueError("launch_id must not be empty")
        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata or {}),
        )


@dataclass(frozen=True)
class OptimizationLaunchResult:
    """Successful result from the atomic launch service."""

    plan: OptimizationRunPlan
    execution: PersistedRunPlanExecutionResult
    manifest: OptimizationLaunchManifest
    manifest_artifacts: OptimizationLaunchManifestArtifacts

    @property
    def manifest_json(self) -> Path:
        return self.manifest_artifacts.manifest_json


class OptimizationLaunchService:
    """Select, persist, execute, and manifest one optimization launch.

    Ordering:

    1. select an execution route from synthesis output;
    2. persist and execute the run plan;
    3. persist a completed launch manifest;
    4. on execution failure, persist a failed manifest when the run-plan
       artifact exists, then re-raise the original exception unchanged.
    """

    def __init__(
        self,
        *,
        executor: PersistedOptimizationRunPlanExecutor,
        route_selector: OptimizationRouteSelector | None = None,
        manifest_builder: OptimizationLaunchManifestBuilder | None = None,
        manifest_persistence: (
            OptimizationLaunchManifestPersistence | None
        ) = None,
    ) -> None:
        self.executor = executor
        self.route_selector = (
            route_selector or OptimizationRouteSelector()
        )
        self.manifest_builder = (
            manifest_builder or OptimizationLaunchManifestBuilder()
        )
        self.manifest_persistence = (
            manifest_persistence
            or OptimizationLaunchManifestPersistence()
        )

    def launch(
        self,
        request: OptimizationLaunchRequest,
    ) -> OptimizationLaunchResult:
        output_directory = request.execution.output_directory
        if output_directory is None:
            raise ValueError(
                "optimization launch requires an output directory"
            )
        output_directory = Path(output_directory)

        plan = self.route_selector.select(request.synthesis)

        try:
            execution = self.executor.execute(
                plan=plan,
                request=request.execution,
            )
        except Exception as exc:
            run_plan_path = self._expected_run_plan_path(
                output_directory
            )
            if run_plan_path.exists():
                failed_manifest = self.manifest_builder.failed(
                    launch_id=request.launch_id,
                    plan=plan,
                    run_plan_path=run_plan_path,
                    error=exc,
                    metadata=request.metadata,
                )
                self.manifest_persistence.persist(
                    failed_manifest,
                    output_directory,
                )
            raise

        manifest = self.manifest_builder.completed(
            launch_id=request.launch_id,
            plan=plan,
            execution=execution,
            metadata=request.metadata,
        )
        manifest_artifacts = self.manifest_persistence.persist(
            manifest,
            output_directory,
        )

        return OptimizationLaunchResult(
            plan=plan,
            execution=execution,
            manifest=manifest,
            manifest_artifacts=manifest_artifacts,
        )

    def _expected_run_plan_path(
        self,
        output_directory: Path,
    ) -> Path:
        return (
            output_directory
            / self.executor.plan_subdirectory
            / self.executor.persistence.DEFAULT_FILENAME
        )
