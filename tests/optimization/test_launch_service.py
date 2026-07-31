from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from openams.optimization.launch_manifest import (
    OptimizationLaunchStatus,
)
from openams.optimization.launch_service import (
    OptimizationLaunchRequest,
    OptimizationLaunchService,
)
from openams.optimization.persisted_plan_executor import (
    PersistedRunPlanExecutionResult,
)
from openams.optimization.plan_executor import (
    RunPlanExecutionRequest,
)
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)
from openams.optimization.run_plan_persistence import (
    OptimizationRunPlanArtifacts,
    OptimizationRunPlanPersistence,
)


@dataclass(frozen=True)
class CycleArtifacts:
    session_artifact_path: Path
    evaluation_artifact_path: Path
    workflow_artifact_path: Path


@dataclass(frozen=True)
class CycleResult:
    artifacts: CycleArtifacts


class SuccessfulExecutor:
    plan_subdirectory = "plan"
    persistence = OptimizationRunPlanPersistence()

    def execute(self, *, plan, request):
        output = Path(request.output_directory)
        plan_artifacts = self.persistence.persist(
            plan,
            output / self.plan_subdirectory,
        )
        session = (
            output / "session" / "optimization_session.json"
        )
        evaluation = (
            output / "evaluation" / "candidate_evaluation.json"
        )
        workflow = (
            output / "workflow" / "workflow_result.json"
        )
        self.persistence.link_session_artifact(
            plan_artifacts.run_plan_json,
            session,
        )
        return PersistedRunPlanExecutionResult(
            cycle_result=CycleResult(
                artifacts=CycleArtifacts(
                    session_artifact_path=session,
                    evaluation_artifact_path=evaluation,
                    workflow_artifact_path=workflow,
                )
            ),
            run_plan_artifacts=plan_artifacts,
            session_artifact_path=session,
        )


class FailingExecutor:
    plan_subdirectory = "plan"
    persistence = OptimizationRunPlanPersistence()

    def __init__(self, error):
        self.error = error

    def execute(self, *, plan, request):
        output = Path(request.output_directory)
        self.persistence.persist(
            plan,
            output / self.plan_subdirectory,
        )
        raise self.error


def launch_request(tmp_path: Path):
    return OptimizationLaunchRequest(
        launch_id="launch_0001",
        synthesis=SynthesisRunInput(
            assignments=({"x": 1.0},),
            metadata={"source": "synthesis"},
        ),
        execution=RunPlanExecutionRequest(
            session_id="session_0001",
            output_directory=tmp_path,
        ),
        metadata={"topology": "two_stage"},
    )


def test_successful_launch_writes_completed_manifest(
    tmp_path: Path,
):
    result = OptimizationLaunchService(
        executor=SuccessfulExecutor(),
    ).launch(launch_request(tmp_path))

    assert result.manifest.status is (
        OptimizationLaunchStatus.COMPLETED
    )
    assert result.manifest.route == "direct_simulation"
    assert result.manifest.reason_code == (
        "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    )
    assert result.manifest.metadata == {
        "topology": "two_stage"
    }
    assert result.manifest_json == (
        tmp_path / "optimization_launch_manifest.json"
    )

    payload = json.loads(
        result.manifest_json.read_text(encoding="utf-8")
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


def test_failure_writes_failed_manifest_and_reraises_same_error(
    tmp_path: Path,
):
    error = RuntimeError("ngspice failed")
    service = OptimizationLaunchService(
        executor=FailingExecutor(error),
    )

    with pytest.raises(RuntimeError) as captured:
        service.launch(launch_request(tmp_path))

    assert captured.value is error

    manifest_path = (
        tmp_path / "optimization_launch_manifest.json"
    )
    payload = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    launch = payload["launch"]

    assert launch["status"] == "failed"
    assert launch["error"] == "ngspice failed"
    assert launch["artifacts"]["run_plan"] == (
        "plan/optimization_run_plan.json"
    )
    assert launch["artifacts"]["session"] is None
    assert launch["artifacts"]["evaluation"] is None
    assert launch["artifacts"]["workflow"] is None


def test_failure_before_plan_persistence_does_not_mask_error(
    tmp_path: Path,
):
    error = RuntimeError("persistence unavailable")

    class EarlyFailExecutor(FailingExecutor):
        def execute(self, *, plan, request):
            raise self.error

    service = OptimizationLaunchService(
        executor=EarlyFailExecutor(error),
    )

    with pytest.raises(RuntimeError) as captured:
        service.launch(launch_request(tmp_path))

    assert captured.value is error
    assert not (
        tmp_path / "optimization_launch_manifest.json"
    ).exists()


def test_output_directory_is_required():
    request = OptimizationLaunchRequest(
        launch_id="launch",
        synthesis=SynthesisRunInput(
            assignments=({"x": 1.0},)
        ),
        execution=RunPlanExecutionRequest(
            session_id="session",
        ),
    )

    with pytest.raises(
        ValueError,
        match="requires an output directory",
    ):
        OptimizationLaunchService(
            executor=SuccessfulExecutor(),
        ).launch(request)


def test_route_selection_happens_before_execution(
    tmp_path: Path,
):
    seen = {}

    class RecordingSelector(OptimizationRouteSelector):
        def select(self, synthesis):
            seen["synthesis"] = synthesis
            return super().select(synthesis)

    service = OptimizationLaunchService(
        executor=SuccessfulExecutor(),
        route_selector=RecordingSelector(),
    )
    request = launch_request(tmp_path)

    result = service.launch(request)

    assert seen["synthesis"] is request.synthesis
    assert result.plan.route.value == "direct_simulation"
