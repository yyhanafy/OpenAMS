from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openams.optimization.adapters import (
    AdapterConfigurationError,
    AssignmentWorkflowExecutorAdapter,
    CandidateEvaluationPersistenceAdapter,
    OptimizationSessionPersistenceAdapter,
    ProposalAssignmentMapper,
    WorkflowBatchExecutorAdapter,
    WorkflowPersistenceAdapter,
)
from openams.optimization.evaluation import (
    CandidateEvaluationSummary,
)
from openams.optimization.session import (
    CandidateProposal,
    OptimizationRoute,
    OptimizationSessionState,
)


def proposal() -> CandidateProposal:
    return CandidateProposal(
        candidate_id="candidate_0000",
        parameters={"vbias": 0.7, "w1": 3.0},
        route=OptimizationRoute.DIRECT_SIMULATION,
        iteration=0,
        proposal_index=0,
    )


def test_workflow_batch_executor_passes_tuple_of_proposals():
    captured = {}

    def workflow(proposals):
        captured["proposals"] = proposals
        return {"ok": True}

    result = WorkflowBatchExecutorAdapter(workflow).execute((proposal(),))

    assert result == {"ok": True}
    assert isinstance(captured["proposals"], tuple)
    assert captured["proposals"][0].candidate_id == "candidate_0000"


def test_assignment_mapper_preserves_candidate_id_and_sorted_values():
    mapped = ProposalAssignmentMapper().map((proposal(),))

    assert mapped == (
        {
            "vbias": 0.7,
            "w1": 3.0,
            "candidate_id": "candidate_0000",
        },
    )


def test_assignment_mapper_can_omit_candidate_id():
    mapped = ProposalAssignmentMapper(
        include_candidate_id=False
    ).map((proposal(),))

    assert mapped == ({"vbias": 0.7, "w1": 3.0},)


def test_assignment_workflow_executor_uses_mapping_boundary():
    captured = {}

    def workflow(assignments):
        captured["assignments"] = assignments
        return "executed"

    result = AssignmentWorkflowExecutorAdapter(workflow).execute(
        (proposal(),)
    )

    assert result == "executed"
    assert captured["assignments"][0]["candidate_id"] == "candidate_0000"


@dataclass
class WorkflowArtifacts:
    workflow_result_json: Path


class FakeWorkflowPersistence:
    def persist(self, workflow_result, output_directory):
        output_directory.mkdir(parents=True, exist_ok=True)
        return WorkflowArtifacts(
            workflow_result_json=output_directory / "workflow_result.json"
        )


def test_workflow_persistence_adapter_uses_subdirectory(tmp_path: Path):
    adapter = WorkflowPersistenceAdapter(
        FakeWorkflowPersistence(),
        subdirectory="workflow_artifacts",
    )

    path = adapter.persist_workflow({"ok": True}, tmp_path)

    assert path == (
        tmp_path / "workflow_artifacts" / "workflow_result.json"
    )


def test_workflow_persistence_adapter_requires_primary_path(tmp_path: Path):
    class BadPersistence:
        def persist(self, workflow_result, output_directory):
            return object()

    adapter = WorkflowPersistenceAdapter(BadPersistence())

    try:
        adapter.persist_workflow({}, tmp_path)
    except AdapterConfigurationError as exc:
        assert "workflow_result_json" in str(exc)
    else:
        raise AssertionError("expected AdapterConfigurationError")


def test_evaluation_persistence_adapter_forwards_workflow_link(
    tmp_path: Path,
):
    captured = {}

    class FakeEvaluationPersistence:
        def persist(
            self,
            summary,
            output_directory,
            *,
            workflow_result_path,
        ):
            captured["summary"] = summary
            captured["directory"] = output_directory
            captured["workflow"] = workflow_result_path

            class Artifacts:
                evaluation_json = output_directory / "candidate_evaluation.json"

            return Artifacts()

    summary = CandidateEvaluationSummary(
        evaluations=(),
        ranking=(),
    )
    workflow_path = tmp_path / "workflow" / "workflow_result.json"

    path = CandidateEvaluationPersistenceAdapter(
        FakeEvaluationPersistence(),
        subdirectory="evaluation_artifacts",
    ).persist_evaluation(
        summary,
        tmp_path,
        workflow_artifact_path=workflow_path,
    )

    assert captured["summary"] is summary
    assert captured["workflow"] == workflow_path
    assert path == (
        tmp_path
        / "evaluation_artifacts"
        / "candidate_evaluation.json"
    )


def test_session_persistence_adapter_forwards_evaluation_link(
    tmp_path: Path,
):
    captured = {}

    class FakeSessionPersistence:
        def persist(
            self,
            state,
            output_directory,
            *,
            evaluation_artifact_path,
        ):
            captured["state"] = state
            captured["directory"] = output_directory
            captured["evaluation"] = evaluation_artifact_path

            class Artifacts:
                session_json = output_directory / "optimization_session.json"

            return Artifacts()

    state = OptimizationSessionState(
        session_id="session",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )
    evaluation_path = (
        tmp_path / "evaluation" / "candidate_evaluation.json"
    )

    path = OptimizationSessionPersistenceAdapter(
        FakeSessionPersistence(),
        subdirectory="session_artifacts",
    ).persist_session(
        state,
        tmp_path,
        evaluation_artifact_path=evaluation_path,
    )

    assert captured["state"] is state
    assert captured["evaluation"] == evaluation_path
    assert path == (
        tmp_path
        / "session_artifacts"
        / "optimization_session.json"
    )
