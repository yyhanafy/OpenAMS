from __future__ import annotations

from pathlib import Path

import pytest

from openams.optimization.application import (
    ContractSearchIterationRequest,
    DirectAssignmentRunRequest,
    OptimizationApplicationError,
    OptimizationApplicationService,
    OptimizationApplicationServices,
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
)
from openams.simulation.results import RawSimulationCaseResult
from openams.simulation.screening import (
    CaseScreeningResult,
    ScreeningOutcome,
)


def make_evaluation(candidate_id: str) -> CandidateEvaluation:
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


class Executor:
    def __init__(self):
        self.batches = []

    def execute(self, proposals):
        proposals = tuple(proposals)
        self.batches.append(proposals)
        return {
            "candidate_ids": [
                proposal.candidate_id
                for proposal in proposals
            ]
        }


class Evaluator:
    def evaluate(self, execution_result):
        evaluations = tuple(
            make_evaluation(candidate_id)
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


def make_service():
    executor = Executor()
    service = OptimizationApplicationService(
        OptimizationApplicationServices(
            executor=executor,
            evaluator=Evaluator(),
        )
    )
    return service, executor


def test_direct_assignments_bypass_contract_search():
    service, executor = make_service()

    result = service.run_direct_assignments(
        DirectAssignmentRunRequest(
            session_id="direct",
            assignments=(
                {"vbias": 0.7, "w1": 3.0},
                {"vbias": 0.8, "w1": 4.0},
            ),
            fixed_parameters={"vdd": 1.8},
        )
    )

    assert result.route is OptimizationRoute.DIRECT_SIMULATION
    assert result.candidate_count == 2
    assert result.valid_count == 2
    assert len(executor.batches) == 1
    assert result.proposals[0].parameters == {
        "vdd": 1.8,
        "vbias": 0.7,
        "w1": 3.0,
    }


def test_direct_run_creates_one_complete_iteration():
    service, _ = make_service()

    result = service.run_direct_assignments(
        DirectAssignmentRunRequest(
            session_id="direct",
            assignments=({"x": 1.0},),
            session_metadata={"topology": "two_stage"},
            iteration_metadata={"route_reason": "fully_resolved"},
        )
    )

    assert len(result.session_state.iterations) == 1
    assert result.session_state.metadata == {
        "topology": "two_stage"
    }
    assert result.session_state.iterations[0].metadata == {
        "route_reason": "fully_resolved"
    }


def test_contract_search_iteration_uses_existing_session():
    service, _ = make_service()
    session = service.create_contract_search_session(
        session_id="search",
        metadata={"seed": 7},
    )

    result = service.run_contract_search_iteration(
        ContractSearchIterationRequest(
            session=session,
            proposer=MidpointProposer(),
            parameter_bounds={"x": (0.0, 2.0)},
            batch_size=1,
            fixed_parameters={"vdd": 1.8},
        )
    )

    assert result.route is OptimizationRoute.CONTRACT_SEARCH
    assert result.proposals[0].parameters == {
        "vdd": 1.8,
        "x": 1.0,
    }
    assert session.state.next_iteration_index == 1


def test_contract_search_can_continue_next_iteration():
    service, _ = make_service()
    session = service.create_contract_search_session(
        session_id="search",
    )

    first = service.run_contract_search_iteration(
        ContractSearchIterationRequest(
            session=session,
            proposer=MidpointProposer(),
            parameter_bounds={"x": (0.0, 2.0)},
            batch_size=1,
        )
    )
    second = service.run_contract_search_iteration(
        ContractSearchIterationRequest(
            session=session,
            proposer=MidpointProposer(),
            parameter_bounds={"x": (2.0, 4.0)},
            batch_size=1,
        )
    )

    assert first.iteration_index == 0
    assert second.iteration_index == 1
    assert len(second.session_state.iterations) == 2


def test_contract_search_rejects_direct_session():
    service, _ = make_service()
    session = OptimizationSession(
        OptimizationSessionState(
            session_id="wrong",
            route=OptimizationRoute.DIRECT_SIMULATION,
        )
    )

    with pytest.raises(
        OptimizationApplicationError,
        match="contract_search",
    ):
        service.run_contract_search_iteration(
            ContractSearchIterationRequest(
                session=session,
                proposer=MidpointProposer(),
                parameter_bounds={"x": (0.0, 1.0)},
                batch_size=1,
            )
        )


def test_resume_contract_search_session_preserves_history():
    service, _ = make_service()
    original = service.create_contract_search_session(
        session_id="resume",
    )
    service.run_contract_search_iteration(
        ContractSearchIterationRequest(
            session=original,
            proposer=MidpointProposer(),
            parameter_bounds={"x": (0.0, 1.0)},
            batch_size=1,
        )
    )

    resumed = service.resume_contract_search_session(
        original.state
    )

    assert resumed.state == original.state
    assert resumed.state.next_iteration_index == 1


def test_resume_rejects_direct_state():
    state = OptimizationSessionState(
        session_id="direct",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )

    with pytest.raises(
        OptimizationApplicationError,
        match="not a contract_search",
    ):
        OptimizationApplicationService.resume_contract_search_session(
            state
        )


def test_requests_validate_required_inputs():
    with pytest.raises(ValueError, match="at least one"):
        DirectAssignmentRunRequest(
            session_id="direct",
            assignments=(),
        )

    service, _ = make_service()
    session = service.create_contract_search_session(
        session_id="search",
    )
    with pytest.raises(ValueError, match="requires unresolved"):
        ContractSearchIterationRequest(
            session=session,
            proposer=MidpointProposer(),
            parameter_bounds={},
            batch_size=1,
        )
