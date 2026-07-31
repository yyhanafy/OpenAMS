from __future__ import annotations

from openams.optimization.evaluation import (
    CandidateEvaluationEngine,
    CandidateState,
    ObjectiveDefinition,
    ObjectiveDirection,
)
from openams.simulation.results import (
    AnalysisStatus,
    MeasurementStatus,
    RawAnalysisResult,
    RawSimulationCaseResult,
    ScalarMeasurement,
)
from openams.simulation.screening import (
    CaseScreeningResult,
    RuleScreeningResult,
    ScreeningOutcome,
)


def make_screening(
    *,
    case_name: str,
    outcome: ScreeningOutcome,
    gain_db: float | None = 72.0,
    power_w: float | None = 1e-3,
    rule_outcomes: tuple[tuple[str, ScreeningOutcome], ...] = (),
):
    measurements = (
        ScalarMeasurement(
            name="gain_db",
            analysis="ac",
            status=(
                MeasurementStatus.PRESENT
                if gain_db is not None
                else MeasurementStatus.MISSING
            ),
            value=gain_db,
            unit="dB",
            source="log",
        ),
        ScalarMeasurement(
            name="power_w",
            analysis="dc",
            status=(
                MeasurementStatus.PRESENT
                if power_w is not None
                else MeasurementStatus.MISSING
            ),
            value=power_w,
            unit="W",
            source="log",
        ),
    )
    raw = RawSimulationCaseResult(
        case_name=case_name,
        execution_succeeded=True,
        analyses=(
            RawAnalysisResult(
                analysis="ac",
                status=AnalysisStatus.SUCCEEDED,
                converged=True,
                measurements=(measurements[0],),
            ),
            RawAnalysisResult(
                analysis="dc",
                status=AnalysisStatus.SUCCEEDED,
                converged=True,
                measurements=(measurements[1],),
            ),
        ),
    )
    rules = tuple(
        RuleScreeningResult(
            rule_name=name,
            measurement=name,
            analysis="ac",
            outcome=rule_outcome,
            actual_value=None,
            expected={},
            unit=None,
        )
        for name, rule_outcome in rule_outcomes
    )
    return CaseScreeningResult(
        case_name=case_name,
        outcome=outcome,
        rules=rules,
        raw_result=raw,
    )


def objective_definitions():
    return (
        ObjectiveDefinition(
            name="gain",
            measurement="gain_db",
            analysis="ac",
            direction=ObjectiveDirection.MAXIMIZE,
            weight=1.0,
            reference_value=60.0,
            normalization_scale=10.0,
        ),
        ObjectiveDefinition(
            name="power",
            measurement="power_w",
            analysis="dc",
            direction=ObjectiveDirection.MINIMIZE,
            weight=2.0,
            reference_value=2e-3,
            normalization_scale=1e-3,
        ),
    )


def test_valid_candidate_gets_aggregate_score():
    engine = CandidateEvaluationEngine(objective_definitions())
    result = engine.evaluate_case(
        make_screening(
            case_name="candidate_1",
            outcome=ScreeningOutcome.PASS,
            gain_db=70.0,
            power_w=1e-3,
        )
    )

    assert result.state is CandidateState.VALID
    assert result.aggregate_score == 3.0
    assert result.optimizer_feedback().feasible is True


def test_failed_screening_is_infeasible():
    engine = CandidateEvaluationEngine(objective_definitions())
    result = engine.evaluate_case(
        make_screening(
            case_name="candidate_1",
            outcome=ScreeningOutcome.FAIL,
            rule_outcomes=(("minimum_gain", ScreeningOutcome.FAIL),),
        )
    )

    assert result.state is CandidateState.INFEASIBLE
    assert result.aggregate_score is None
    assert result.failure_reasons == ("minimum_gain",)
    assert result.optimizer_feedback().feasible is False


def test_unknown_screening_remains_unknown():
    engine = CandidateEvaluationEngine(objective_definitions())
    result = engine.evaluate_case(
        make_screening(
            case_name="candidate_1",
            outcome=ScreeningOutcome.UNKNOWN,
            rule_outcomes=(("minimum_ugb", ScreeningOutcome.UNKNOWN),),
        )
    )

    assert result.state is CandidateState.UNKNOWN
    assert result.optimizer_feedback().feasible is None


def test_missing_required_objective_makes_passing_candidate_unknown():
    engine = CandidateEvaluationEngine(objective_definitions())
    result = engine.evaluate_case(
        make_screening(
            case_name="candidate_1",
            outcome=ScreeningOutcome.PASS,
            gain_db=None,
        )
    )

    assert result.state is CandidateState.UNKNOWN
    assert "objective:gain" in result.unknown_reasons


def test_optional_missing_objective_does_not_block_validity():
    objectives = (
        ObjectiveDefinition(
            name="gain",
            measurement="gain_db",
            analysis="ac",
            direction=ObjectiveDirection.MAXIMIZE,
        ),
        ObjectiveDefinition(
            name="power",
            measurement="power_w",
            analysis="dc",
            direction=ObjectiveDirection.MINIMIZE,
            required=False,
        ),
    )
    engine = CandidateEvaluationEngine(objectives)
    result = engine.evaluate_case(
        make_screening(
            case_name="candidate_1",
            outcome=ScreeningOutcome.PASS,
            power_w=None,
        )
    )

    assert result.state is CandidateState.VALID
    assert result.aggregate_score == 72.0


def test_ranking_is_score_descending_then_candidate_id():
    engine = CandidateEvaluationEngine(
        (
            ObjectiveDefinition(
                name="gain",
                measurement="gain_db",
                analysis="ac",
                direction=ObjectiveDirection.MAXIMIZE,
            ),
        )
    )

    summary = engine.evaluate_many(
        (
            make_screening(
                case_name="candidate_b",
                outcome=ScreeningOutcome.PASS,
                gain_db=72.0,
            ),
            make_screening(
                case_name="candidate_a",
                outcome=ScreeningOutcome.PASS,
                gain_db=72.0,
            ),
            make_screening(
                case_name="candidate_c",
                outcome=ScreeningOutcome.PASS,
                gain_db=70.0,
            ),
        )
    )

    assert [item.evaluation.candidate_id for item in summary.ranking] == [
        "candidate_a",
        "candidate_b",
        "candidate_c",
    ]
    assert [item.rank for item in summary.ranking] == [1, 2, 3]


def test_infeasible_and_unknown_candidates_are_not_ranked():
    engine = CandidateEvaluationEngine(
        (
            ObjectiveDefinition(
                name="gain",
                measurement="gain_db",
                analysis="ac",
                direction=ObjectiveDirection.MAXIMIZE,
            ),
        )
    )

    summary = engine.evaluate_many(
        (
            make_screening(
                case_name="valid",
                outcome=ScreeningOutcome.PASS,
            ),
            make_screening(
                case_name="failed",
                outcome=ScreeningOutcome.FAIL,
            ),
            make_screening(
                case_name="unknown",
                outcome=ScreeningOutcome.UNKNOWN,
            ),
        )
    )

    assert summary.valid_count == 1
    assert summary.infeasible_count == 1
    assert summary.unknown_count == 1
    assert [item.evaluation.candidate_id for item in summary.ranking] == [
        "valid"
    ]


def test_evaluation_preserves_screening_identity():
    screening = make_screening(
        case_name="candidate_1",
        outcome=ScreeningOutcome.PASS,
    )
    engine = CandidateEvaluationEngine(objective_definitions())

    evaluation = engine.evaluate_case(screening)

    assert evaluation.screening_result is screening
