from __future__ import annotations

from pathlib import Path

import pytest

from openams.optimization.cycle import (
    OptimizationCycleError,
    OptimizationCycleOrchestrator,
    OptimizationCyclePersistence,
)
from openams.optimization.evaluation import (
    CandidateEvaluation,
    CandidateEvaluationSummary,
    CandidateState,
    RankedCandidate,
)
from openams.optimization.proposers import MidpointProposer
from openams.optimization.session import (
    OptimizationRoute,
    OptimizationSession,
    OptimizationSessionState,
    ProposalRequest,
    ProposalStatus,
)
from openams.simulation.results import RawSimulationCaseResult
from openams.simulation.screening import (
    CaseScreeningResult,
    ScreeningOutcome,
)


def evaluation(candidate_id: str) -> CandidateEvaluation:
    raw = RawSimulationCaseResult(
        case_name=candidate_id,
        execution_succeeded=True,
        analyses=(),
    )
    screening = CaseScreeningResult(
        case_name=candidate_id,
        outcome=ScreeningOutcome.PASS,
        rules=(),
        raw_result=raw,
    )
    return CandidateEvaluation(
        candidate_id=candidate_id,
        state=CandidateState.VALID,
        aggregate_score=1.0,
        objectives=(),
        screening_result=screening,
    )


class RecordingExecutor:
    def __init__(self):
        self.proposals = None

    def execute(self, proposals):
        self.proposals = tuple(proposals)
        return {"candidate_ids": [item.candidate_id for item in proposals]}


class MatchingEvaluator:
    def evaluate(self, execution_result):
        evaluations = tuple(
            evaluation(candidate_id)
            for candidate_id in execution_result["candidate_ids"]
        )
        ranking = tuple(
            RankedCandidate(rank=index + 1, evaluation=item)
            for index, item in enumerate(evaluations)
        )
        return CandidateEvaluationSummary(
            evaluations=evaluations,
            ranking=ranking,
        )


def make_session_and_request():
    state = OptimizationSessionState(
        session_id="cycle",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(state)
    request = ProposalRequest(
        session=state,
        batch_size=1,
        parameter_bounds={"x": (0.0, 2.0)},
        fixed_parameters={"bias": 0.7},
    )
    return session, request


def test_cycle_runs_proposal_execution_evaluation_and_feedback():
    session, request = make_session_and_request()
    executor = RecordingExecutor()
    orchestrator = OptimizationCycleOrchestrator(
        executor=executor,
        evaluator=MatchingEvaluator(),
    )

    result = orchestrator.run(
        session=session,
        proposer=MidpointProposer(),
        request=request,
    )

    assert result.iteration_index == 0
    assert result.candidate_count == 1
    assert result.valid_count == 1
    assert result.infeasible_count == 0
    assert result.unknown_count == 0
    assert executor.proposals == result.proposals

    record = result.session_state.iterations[0].records[0]
    assert record.status is ProposalStatus.EVALUATED
    assert record.feedback.feasible is True


def test_cycle_preserves_route_and_parameters():
    session, request = make_session_and_request()
    result = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=MatchingEvaluator(),
    ).run(
        session=session,
        proposer=MidpointProposer(),
        request=request,
    )

    assert result.route is OptimizationRoute.CONTRACT_SEARCH
    assert result.proposals[0].parameters == {
        "bias": 0.7,
        "x": 1.0,
    }


def test_cycle_rejects_missing_feedback():
    session, request = make_session_and_request()

    class EmptyEvaluator:
        def evaluate(self, execution_result):
            return CandidateEvaluationSummary(
                evaluations=(),
                ranking=(),
            )

    orchestrator = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=EmptyEvaluator(),
    )

    with pytest.raises(
        OptimizationCycleError,
        match="missing feedback",
    ):
        orchestrator.run(
            session=session,
            proposer=MidpointProposer(),
            request=request,
        )


def test_cycle_rejects_request_for_stale_session():
    session, request = make_session_and_request()
    session.record_proposals(
        MidpointProposer().propose(request)
    )

    orchestrator = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=MatchingEvaluator(),
    )

    with pytest.raises(
        OptimizationCycleError,
        match="does not match current",
    ):
        orchestrator.run(
            session=session,
            proposer=MidpointProposer(),
            request=request,
        )


def test_cycle_persists_artifacts_in_dependency_order(tmp_path: Path):
    calls = []

    class WorkflowPersister:
        def persist_workflow(self, execution_result, output_directory):
            calls.append(("workflow", execution_result))
            return output_directory / "workflow_result.json"

    class EvaluationPersister:
        def persist_evaluation(
            self,
            summary,
            output_directory,
            *,
            workflow_artifact_path,
        ):
            calls.append(("evaluation", workflow_artifact_path))
            return output_directory / "candidate_evaluation.json"

    class SessionPersister:
        def persist_session(
            self,
            state,
            output_directory,
            *,
            evaluation_artifact_path,
        ):
            calls.append(("session", evaluation_artifact_path))
            return output_directory / "optimization_session.json"

    session, request = make_session_and_request()
    orchestrator = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=MatchingEvaluator(),
        persistence=OptimizationCyclePersistence(
            workflow=WorkflowPersister(),
            evaluation=EvaluationPersister(),
            session=SessionPersister(),
        ),
    )

    result = orchestrator.run(
        session=session,
        proposer=MidpointProposer(),
        request=request,
        output_directory=tmp_path,
    )

    assert [item[0] for item in calls] == [
        "workflow",
        "evaluation",
        "session",
    ]
    assert calls[1][1] == tmp_path / "workflow_result.json"
    assert calls[2][1] == tmp_path / "candidate_evaluation.json"
    assert (
        result.artifacts.session_artifact_path
        == tmp_path / "optimization_session.json"
    )


def test_cycle_without_output_directory_performs_no_persistence():
    class FailingPersister:
        def persist_workflow(self, execution_result, output_directory):
            raise AssertionError("persistence should not run")

    session, request = make_session_and_request()
    result = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=MatchingEvaluator(),
        persistence=OptimizationCyclePersistence(
            workflow=FailingPersister(),
        ),
    ).run(
        session=session,
        proposer=MidpointProposer(),
        request=request,
    )

    assert result.artifacts.workflow_artifact_path is None


def test_cycle_metadata_is_attached_to_iteration():
    session, request = make_session_and_request()
    result = OptimizationCycleOrchestrator(
        executor=RecordingExecutor(),
        evaluator=MatchingEvaluator(),
    ).run(
        session=session,
        proposer=MidpointProposer(),
        request=request,
        metadata={"phase": "smoke"},
    )

    assert result.session_state.iterations[0].metadata == {
        "phase": "smoke"
    }
