from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from openams.optimization.persisted_plan_executor import (
    PersistedOptimizationRunPlanExecutor,
    PersistedRunPlanExecutionError,
)
from openams.optimization.plan_executor import (
    RunPlanExecutionRequest,
)
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)


def direct_plan():
    return OptimizationRouteSelector().select(
        SynthesisRunInput(
            assignments=({"x": 1.0},),
            metadata={"source": "synthesis"},
        )
    )


@dataclass(frozen=True)
class Artifacts:
    session_artifact_path: Path | None


@dataclass(frozen=True)
class CycleResult:
    artifacts: Artifacts


class FakeExecutor:
    def __init__(self, session_path: Path | None):
        self.session_path = session_path
        self.calls = []

    def execute(self, *, plan, request):
        self.calls.append((plan, request))
        return CycleResult(
            artifacts=Artifacts(
                session_artifact_path=self.session_path
            )
        )


def test_persist_before_execute_and_link_session(tmp_path: Path):
    session_path = (
        tmp_path / "session" / "optimization_session.json"
    )
    executor = FakeExecutor(session_path)
    service = PersistedOptimizationRunPlanExecutor(
        executor=executor,
    )

    result = service.execute(
        plan=direct_plan(),
        request=RunPlanExecutionRequest(
            session_id="direct",
            output_directory=tmp_path,
        ),
    )

    assert result.run_plan_json == (
        tmp_path / "plan" / "optimization_run_plan.json"
    )
    assert result.session_artifact_path == session_path
    assert len(executor.calls) == 1

    payload = json.loads(
        result.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["plan"]["reason_code"] == (
        "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    )
    assert payload["links"]["optimization_session"] == str(
        session_path
    )


def test_relative_session_link_is_used_inside_plan_tree(
    tmp_path: Path,
):
    session_path = (
        tmp_path
        / "plan"
        / "session"
        / "optimization_session.json"
    )
    service = PersistedOptimizationRunPlanExecutor(
        executor=FakeExecutor(session_path),
    )

    result = service.execute(
        plan=direct_plan(),
        request=RunPlanExecutionRequest(
            session_id="direct",
            output_directory=tmp_path,
        ),
    )

    payload = json.loads(
        result.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["links"]["optimization_session"] == (
        "session/optimization_session.json"
    )


def test_output_directory_is_required():
    service = PersistedOptimizationRunPlanExecutor(
        executor=FakeExecutor(None),
    )

    with pytest.raises(
        PersistedRunPlanExecutionError,
        match="requires an output directory",
    ):
        service.execute(
            plan=direct_plan(),
            request=RunPlanExecutionRequest(
                session_id="direct",
            ),
        )


def test_session_artifact_can_be_optional(tmp_path: Path):
    service = PersistedOptimizationRunPlanExecutor(
        executor=FakeExecutor(None),
        require_session_artifact=False,
    )

    result = service.execute(
        plan=direct_plan(),
        request=RunPlanExecutionRequest(
            session_id="direct",
            output_directory=tmp_path,
        ),
    )

    assert result.session_artifact_path is None
    payload = json.loads(
        result.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["links"] == {}


def test_required_session_artifact_is_enforced(tmp_path: Path):
    service = PersistedOptimizationRunPlanExecutor(
        executor=FakeExecutor(None),
        require_session_artifact=True,
    )

    with pytest.raises(
        PersistedRunPlanExecutionError,
        match="did not expose a session artifact",
    ):
        service.execute(
            plan=direct_plan(),
            request=RunPlanExecutionRequest(
                session_id="direct",
                output_directory=tmp_path,
            ),
        )


def test_session_json_alias_is_supported(tmp_path: Path):
    session_path = tmp_path / "optimization_session.json"

    @dataclass(frozen=True)
    class AliasArtifacts:
        session_json: Path

    @dataclass(frozen=True)
    class AliasResult:
        artifacts: AliasArtifacts

    class AliasExecutor:
        def execute(self, *, plan, request):
            return AliasResult(
                artifacts=AliasArtifacts(
                    session_json=session_path
                )
            )

    result = PersistedOptimizationRunPlanExecutor(
        executor=AliasExecutor(),
    ).execute(
        plan=direct_plan(),
        request=RunPlanExecutionRequest(
            session_id="direct",
            output_directory=tmp_path,
        ),
    )

    assert result.session_artifact_path == session_path
