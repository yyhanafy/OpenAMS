from __future__ import annotations

import pytest

from openams.optimization.evaluation import (
    CandidateState,
    OptimizerFeedback,
)
from openams.optimization.session import (
    CandidateProposal,
    OptimizationRoute,
    OptimizationSession,
    OptimizationSessionError,
    OptimizationSessionState,
    ProposalRequest,
    ProposalStatus,
)


def proposal(
    candidate_id: str,
    *,
    route: OptimizationRoute,
    iteration: int,
    index: int,
):
    return CandidateProposal(
        candidate_id=candidate_id,
        parameters={"x": float(index + 1)},
        route=route,
        iteration=iteration,
        proposal_index=index,
    )


def test_direct_simulation_request_rejects_ranges():
    state = OptimizationSessionState(
        session_id="direct",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )

    with pytest.raises(ValueError, match="must not contain unresolved ranges"):
        ProposalRequest(
            session=state,
            batch_size=1,
            parameter_bounds={"x": (0.0, 1.0)},
        )


def test_contract_search_requires_ranges():
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )

    with pytest.raises(ValueError, match="requires unresolved"):
        ProposalRequest(
            session=state,
            batch_size=1,
            parameter_bounds={},
            fixed_parameters={"x": 1.0},
        )


def test_record_proposals_appends_immutable_iteration():
    initial = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(initial)

    updated = session.record_proposals(
        (
            proposal(
                "candidate_0000",
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=0,
                index=0,
            ),
            proposal(
                "candidate_0001",
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=0,
                index=1,
            ),
        )
    )

    assert initial.iterations == ()
    assert len(updated.iterations) == 1
    assert updated.candidate_count == 2
    assert updated.iterations[0].records[0].status is ProposalStatus.PROPOSED


def test_feedback_updates_matching_records_only():
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(state)
    session.record_proposals(
        (
            proposal(
                "candidate_0000",
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=0,
                index=0,
            ),
            proposal(
                "candidate_0001",
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=0,
                index=1,
            ),
        )
    )

    updated = session.apply_feedback(
        0,
        (
            OptimizerFeedback(
                candidate_id="candidate_0000",
                feasible=True,
                objective_value=1.5,
                state=CandidateState.VALID,
            ),
        ),
    )

    records = updated.iterations[0].records
    assert records[0].status is ProposalStatus.EVALUATED
    assert records[1].status is ProposalStatus.PROPOSED
    assert updated.evaluated_count == 1
    assert updated.valid_count == 1


def test_feedback_for_unknown_candidate_is_rejected():
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(state)
    session.record_proposals(
        (
            proposal(
                "candidate_0000",
                route=OptimizationRoute.CONTRACT_SEARCH,
                iteration=0,
                index=0,
            ),
        )
    )

    with pytest.raises(
        OptimizationSessionError,
        match="unknown candidates",
    ):
        session.apply_feedback(
            0,
            (
                OptimizerFeedback(
                    candidate_id="candidate_9999",
                    feasible=False,
                    objective_value=None,
                    state=CandidateState.INFEASIBLE,
                ),
            ),
        )


def test_candidate_ids_must_be_unique_across_session():
    first = proposal(
        "candidate_0000",
        route=OptimizationRoute.CONTRACT_SEARCH,
        iteration=0,
        index=0,
    )
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(state)
    session.record_proposals((first,))

    duplicate = proposal(
        "candidate_0000",
        route=OptimizationRoute.CONTRACT_SEARCH,
        iteration=1,
        index=0,
    )

    with pytest.raises(ValueError, match="duplicate candidate"):
        session.record_proposals((duplicate,))


def test_propose_and_record_checks_batch_size():
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    session = OptimizationSession(state)
    request = ProposalRequest(
        session=state,
        batch_size=2,
        parameter_bounds={"x": (0.0, 1.0)},
    )

    class BadProposer:
        def propose(self, request):
            return (
                proposal(
                    "candidate_0000",
                    route=OptimizationRoute.CONTRACT_SEARCH,
                    iteration=0,
                    index=0,
                ),
            )

    with pytest.raises(OptimizationSessionError, match="expected 2"):
        session.propose_and_record(BadProposer(), request)


def test_proposer_protocol_remains_optimizer_neutral():
    state = OptimizationSessionState(
        session_id="search",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    request = ProposalRequest(
        session=state,
        batch_size=2,
        parameter_bounds={"x": (0.0, 1.0)},
        fixed_parameters={"bias": 0.7},
    )

    class DeterministicProposer:
        def propose(self, request):
            return tuple(
                CandidateProposal(
                    candidate_id=f"candidate_{index:04d}",
                    parameters={
                        "x": float(index),
                        **request.fixed_parameters,
                    },
                    route=request.session.route,
                    iteration=request.session.next_iteration_index,
                    proposal_index=index,
                    source="deterministic_test",
                )
                for index in range(request.batch_size)
            )

    session = OptimizationSession(state)
    updated = session.propose_and_record(
        DeterministicProposer(),
        request,
    )

    assert updated.candidate_count == 2
    assert (
        updated.iterations[0].records[1].proposal.parameters["bias"]
        == 0.7
    )

def test_direct_simulation_request_allows_assignment_only_proposer():
    state = OptimizationSessionState(
        session_id="direct_assignment_only",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )

    request = ProposalRequest(
        session=state,
        batch_size=1,
        parameter_bounds={},
        fixed_parameters={},
    )

    assert request.parameter_bounds == {}
    assert request.fixed_parameters == {}

