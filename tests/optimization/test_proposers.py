from __future__ import annotations

import pytest

from openams.optimization.proposers import (
    DirectAssignmentProposer,
    GridSearchProposer,
    MidpointProposer,
    ProposalGenerationError,
)
from openams.optimization.session import (
    OptimizationRoute,
    OptimizationSessionState,
    ProposalRequest,
)


def direct_request(batch_size: int = 2) -> ProposalRequest:
    state = OptimizationSessionState(
        session_id="direct_session",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )
    return ProposalRequest(
        session=state,
        batch_size=batch_size,
        parameter_bounds={},
        fixed_parameters={"vdd": 1.8},
    )


def search_request(batch_size: int = 3) -> ProposalRequest:
    state = OptimizationSessionState(
        session_id="search session",
        route=OptimizationRoute.CONTRACT_SEARCH,
    )
    return ProposalRequest(
        session=state,
        batch_size=batch_size,
        parameter_bounds={
            "vbias": (0.6, 0.8),
            "w1": (2.0, 4.0),
        },
        fixed_parameters={"vdd": 1.8},
    )


def test_direct_assignment_proposer_emits_resolved_candidates():
    proposer = DirectAssignmentProposer(
        (
            {"vbias": 0.7, "w1": 3.0},
            {"vbias": 0.8, "w1": 4.0},
        )
    )

    proposals = proposer.propose(direct_request())

    assert len(proposals) == 2
    assert proposals[0].route is OptimizationRoute.DIRECT_SIMULATION
    assert proposals[0].parameters == {
        "vdd": 1.8,
        "vbias": 0.7,
        "w1": 3.0,
    }
    assert proposals[0].candidate_id == (
        "direct_session_iter_0000_candidate_0000"
    )


def test_direct_assignment_conflict_is_rejected():
    state = OptimizationSessionState(
        session_id="direct",
        route=OptimizationRoute.DIRECT_SIMULATION,
    )
    request = ProposalRequest(
        session=state,
        batch_size=1,
        parameter_bounds={},
        fixed_parameters={"vdd": 1.8},
    )
    proposer = DirectAssignmentProposer(({"vdd": 2.5},))

    with pytest.raises(
        ProposalGenerationError,
        match="conflicts with fixed",
    ):
        proposer.propose(request)


def test_direct_proposer_rejects_wrong_route():
    proposer = DirectAssignmentProposer(({"x": 1.0},))

    with pytest.raises(
        ProposalGenerationError,
        match="direct_simulation",
    ):
        proposer.propose(search_request(batch_size=1))


def test_grid_search_is_deterministic():
    proposer = GridSearchProposer(points_per_dimension=2)

    proposals = proposer.propose(search_request(batch_size=4))

    assert [proposal.parameters for proposal in proposals] == [
        {"vdd": 1.8, "vbias": 0.6, "w1": 2.0},
        {"vdd": 1.8, "vbias": 0.6, "w1": 4.0},
        {"vdd": 1.8, "vbias": 0.8, "w1": 2.0},
        {"vdd": 1.8, "vbias": 0.8, "w1": 4.0},
    ]
    assert proposals[0].candidate_id == (
        "search_session_iter_0000_candidate_0000"
    )


def test_grid_search_rejects_batch_larger_than_grid():
    proposer = GridSearchProposer(points_per_dimension=2)

    with pytest.raises(
        ProposalGenerationError,
        match="grid contains only 4",
    ):
        proposer.propose(search_request(batch_size=5))


def test_midpoint_proposer_merges_fixed_and_midpoint_parameters():
    proposal = MidpointProposer().propose(
        search_request(batch_size=1)
    )[0]

    assert proposal.parameters == {
        "vdd": 1.8,
        "vbias": 0.7,
        "w1": 3.0,
    }
    assert proposal.metadata["reference_proposer"] == "midpoint"


def test_midpoint_supports_one_candidate_only():
    with pytest.raises(
        ProposalGenerationError,
        match="batch_size=1",
    ):
        MidpointProposer().propose(search_request(batch_size=2))


def test_candidate_ids_include_resumed_iteration():
    state = OptimizationSessionState(
        session_id="resume",
        route=OptimizationRoute.CONTRACT_SEARCH,
        iterations=(),
    )
    request = ProposalRequest(
        session=state,
        batch_size=1,
        parameter_bounds={"x": (0.0, 1.0)},
    )

    proposal = MidpointProposer().propose(request)[0]

    assert proposal.iteration == state.next_iteration_index
    assert proposal.candidate_id == "resume_iter_0000_candidate_0000"
