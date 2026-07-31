from __future__ import annotations

import pytest

from openams.optimization.application import (
    OptimizationApplicationService,
    OptimizationApplicationServices,
)
from openams.optimization.evaluation import (
    CandidateEvaluation,
    CandidateEvaluationSummary,
    CandidateState,
    RankedCandidate,
)
from openams.optimization.plan_executor import (
    OptimizationRunPlanExecutor,
    RunPlanExecutionError,
    RunPlanExecutionRequest,
)
from openams.optimization.proposers import MidpointProposer
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)
from openams.optimization.session import OptimizationRoute
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


class Executor:
    def execute(self, proposals):
        return {
            "candidate_ids": [
                proposal.candidate_id
                for proposal in proposals
            ]
        }


class Evaluator:
    def evaluate(self, execution_result):
        evaluations = tuple(
            evaluation(candidate_id)
            for candidate_id in execution_result["candidate_ids"]
        )
        return CandidateEvaluationSummary(
            evaluations=evaluations,
            ranking=tuple(
                RankedCandidate(rank=index + 1, evaluation=item)
                for index, item in enumerate(evaluations)
            ),
        )


def make_executor():
    application = OptimizationApplicationService(
        OptimizationApplicationServices(
            executor=Executor(),
            evaluator=Evaluator(),
        )
    )
    return OptimizationRunPlanExecutor(application)


def test_direct_plan_dispatches_without_contract_search():
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(
            assignments=({"x": 1.0}, {"x": 2.0}),
            fixed_parameters={"vdd": 1.8},
            metadata={"source": "synthesis"},
        )
    )

    result = make_executor().execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="direct",
            session_metadata={"topology": "two_stage"},
        ),
    )

    assert result.route is OptimizationRoute.DIRECT_SIMULATION
    assert result.candidate_count == 2
    assert result.session_state.metadata["source"] == "synthesis"
    assert result.session_state.metadata["topology"] == "two_stage"
    assert (
        result.session_state.metadata["route_reason_code"]
        == "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    )
    assert (
        result.session_state.iterations[0]
        .metadata["route_reason_code"]
        == "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    )


def test_direct_plan_rejects_proposer():
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(assignments=({"x": 1.0},))
    )

    with pytest.raises(
        RunPlanExecutionError,
        match="must not supply a proposer",
    ):
        make_executor().execute(
            plan=plan,
            request=RunPlanExecutionRequest(
                session_id="direct",
                proposer=MidpointProposer(),
            ),
        )


def test_contract_plan_creates_session_and_runs_iteration():
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(
            unresolved_ranges={"x": (0.0, 2.0)},
            fixed_parameters={"vdd": 1.8},
        )
    )

    result = make_executor().execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="search",
            proposer=MidpointProposer(),
        ),
    )

    assert result.route is OptimizationRoute.CONTRACT_SEARCH
    assert result.proposals[0].parameters == {
        "vdd": 1.8,
        "x": 1.0,
    }
    assert (
        result.session_state.metadata["route_reason_code"]
        == "UNRESOLVED_PARAMETER_RANGES_PRESENT"
    )
    assert (
        result.session_state.iterations[0]
        .metadata["route_reason_code"]
        == "UNRESOLVED_PARAMETER_RANGES_PRESENT"
    )


def test_contract_plan_requires_proposer():
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(unresolved_ranges={"x": (0.0, 1.0)})
    )

    with pytest.raises(
        RunPlanExecutionError,
        match="requires a candidate proposer",
    ):
        make_executor().execute(
            plan=plan,
            request=RunPlanExecutionRequest(
                session_id="search",
            ),
        )


def test_contract_plan_can_continue_supplied_session():
    executor = make_executor()
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(unresolved_ranges={"x": (0.0, 1.0)})
    )
    first = executor.execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="search",
            proposer=MidpointProposer(),
        ),
    )

    from openams.optimization.session import OptimizationSession

    resumed = OptimizationSession(first.session_state)
    second = executor.execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="search",
            proposer=MidpointProposer(),
            session=resumed,
        ),
    )

    assert first.iteration_index == 0
    assert second.iteration_index == 1
    assert len(second.session_state.iterations) == 2


def test_supplied_session_identifier_must_match():
    application = OptimizationApplicationService(
        OptimizationApplicationServices(
            executor=Executor(),
            evaluator=Evaluator(),
        )
    )
    session = application.create_contract_search_session(
        session_id="actual",
    )
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(unresolved_ranges={"x": (0.0, 1.0)})
    )

    with pytest.raises(
        RunPlanExecutionError,
        match="session_id does not match",
    ):
        OptimizationRunPlanExecutor(application).execute(
            plan=plan,
            request=RunPlanExecutionRequest(
                session_id="different",
                proposer=MidpointProposer(),
                session=session,
            ),
        )


def test_contract_batch_size_is_forwarded():
    from openams.optimization.proposers import GridSearchProposer

    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(
            unresolved_ranges={
                "x": (0.0, 1.0),
                "y": (10.0, 20.0),
            }
        )
    )

    result = make_executor().execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="search",
            proposer=GridSearchProposer(points_per_dimension=2),
            batch_size=4,
        ),
    )

    assert result.candidate_count == 4
