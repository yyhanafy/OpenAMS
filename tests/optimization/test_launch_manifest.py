from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from openams.optimization.launch_manifest import (
    LaunchManifestError,
    OptimizationLaunchArtifacts,
    OptimizationLaunchManifest,
    OptimizationLaunchManifestPersistence,
    OptimizationLaunchStatus,
)
from openams.optimization.launch_manifest_builder import (
    OptimizationLaunchManifestBuilder,
)
from openams.optimization.persisted_plan_executor import (
    PersistedRunPlanExecutionResult,
)
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)
from openams.optimization.run_plan_persistence import (
    OptimizationRunPlanArtifacts,
)


def plan():
    return OptimizationRouteSelector().select(
        SynthesisRunInput(assignments=({"x": 1.0},))
    )


def test_manifest_persist_and_load_with_relative_links(
    tmp_path: Path,
):
    run_plan = tmp_path / "plan" / "optimization_run_plan.json"
    session = tmp_path / "session" / "optimization_session.json"
    evaluation = (
        tmp_path / "evaluation" / "candidate_evaluation.json"
    )
    workflow = tmp_path / "workflow" / "workflow_result.json"

    manifest = OptimizationLaunchManifest(
        launch_id="launch_0001",
        status=OptimizationLaunchStatus.COMPLETED,
        route="direct_simulation",
        reason_code="ALL_ASSIGNMENTS_FULLY_RESOLVED",
        artifacts=OptimizationLaunchArtifacts(
            run_plan=run_plan,
            session=session,
            evaluation=evaluation,
            workflow=workflow,
        ),
        metadata={"topology": "two_stage"},
    )

    persistence = OptimizationLaunchManifestPersistence()
    artifacts = persistence.persist(manifest, tmp_path)
    restored = persistence.load(artifacts.manifest_json)

    assert restored == manifest

    payload = json.loads(
        artifacts.manifest_json.read_text(encoding="utf-8")
    )
    links = payload["launch"]["artifacts"]
    assert links["run_plan"] == (
        "plan/optimization_run_plan.json"
    )
    assert links["session"] == (
        "session/optimization_session.json"
    )
    assert links["evaluation"] == (
        "evaluation/candidate_evaluation.json"
    )
    assert links["workflow"] == (
        "workflow/workflow_result.json"
    )


def test_failed_manifest_requires_error(tmp_path: Path):
    with pytest.raises(ValueError, match="requires an error"):
        OptimizationLaunchManifest(
            launch_id="launch",
            status=OptimizationLaunchStatus.FAILED,
            route="contract_search",
            reason_code="UNRESOLVED_PARAMETER_RANGES_PRESENT",
            artifacts=OptimizationLaunchArtifacts(
                run_plan=tmp_path / "plan.json"
            ),
        )


def test_non_failed_manifest_rejects_error(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="must not carry an error",
    ):
        OptimizationLaunchManifest(
            launch_id="launch",
            status=OptimizationLaunchStatus.COMPLETED,
            route="direct_simulation",
            reason_code="ALL_ASSIGNMENTS_FULLY_RESOLVED",
            error="unexpected",
            artifacts=OptimizationLaunchArtifacts(
                run_plan=tmp_path / "plan.json"
            ),
        )


def test_invalid_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "optimization_launch_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "artifact_type": "optimization_launch_manifest",
                "launch": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LaunchManifestError, match="unsupported"):
        OptimizationLaunchManifestPersistence().load(path)


@dataclass(frozen=True)
class CycleArtifacts:
    session_artifact_path: Path
    evaluation_artifact_path: Path
    workflow_artifact_path: Path


@dataclass(frozen=True)
class CycleResult:
    artifacts: CycleArtifacts


def test_builder_collects_completed_artifact_chain(
    tmp_path: Path,
):
    run_plan = tmp_path / "plan" / "optimization_run_plan.json"
    session = tmp_path / "session" / "optimization_session.json"
    evaluation = (
        tmp_path / "evaluation" / "candidate_evaluation.json"
    )
    workflow = tmp_path / "workflow" / "workflow_result.json"

    execution = PersistedRunPlanExecutionResult(
        cycle_result=CycleResult(
            artifacts=CycleArtifacts(
                session_artifact_path=session,
                evaluation_artifact_path=evaluation,
                workflow_artifact_path=workflow,
            )
        ),
        run_plan_artifacts=OptimizationRunPlanArtifacts(
            run_plan_json=run_plan
        ),
        session_artifact_path=session,
    )

    manifest = OptimizationLaunchManifestBuilder().completed(
        launch_id="launch_0001",
        plan=plan(),
        execution=execution,
    )

    assert manifest.status is OptimizationLaunchStatus.COMPLETED
    assert manifest.artifacts.run_plan == run_plan
    assert manifest.artifacts.session == session
    assert manifest.artifacts.evaluation == evaluation
    assert manifest.artifacts.workflow == workflow


def test_builder_creates_failed_manifest(tmp_path: Path):
    manifest = OptimizationLaunchManifestBuilder().failed(
        launch_id="launch_failed",
        plan=plan(),
        run_plan_path=tmp_path / "optimization_run_plan.json",
        error=RuntimeError("ngspice failed"),
    )

    assert manifest.status is OptimizationLaunchStatus.FAILED
    assert manifest.error == "ngspice failed"
    assert manifest.artifacts.session is None
