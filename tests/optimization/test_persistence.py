from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from openams.optimization.evaluation import (
    CandidateEvaluation,
    CandidateEvaluationSummary,
    CandidateState,
    ObjectiveComponent,
    ObjectiveDirection,
    RankedCandidate,
)
from openams.optimization.persistence import (
    CandidateEvaluationPersistence,
    EvaluationPersistenceError,
    SCHEMA_VERSION,
    objective_component_rows,
    ranking_rows,
)
from openams.simulation.results import (
    RawSimulationCaseResult,
)
from openams.simulation.screening import (
    CaseScreeningResult,
    ScreeningOutcome,
)


def make_summary() -> CandidateEvaluationSummary:
    raw_a = RawSimulationCaseResult(
        case_name="candidate_a",
        execution_succeeded=True,
        analyses=(),
    )
    screen_a = CaseScreeningResult(
        case_name="candidate_a",
        outcome=ScreeningOutcome.PASS,
        rules=(),
        raw_result=raw_a,
    )
    component_a = ObjectiveComponent(
        name="gain",
        measurement="gain_db",
        analysis="ac",
        direction=ObjectiveDirection.MAXIMIZE,
        status="available",
        raw_value=72.0,
        normalized_value=1.2,
        weighted_value=1.2,
        weight=1.0,
        unit="dB",
    )
    eval_a = CandidateEvaluation(
        candidate_id="candidate_a",
        state=CandidateState.VALID,
        aggregate_score=1.2,
        objectives=(component_a,),
        screening_result=screen_a,
    )

    raw_b = RawSimulationCaseResult(
        case_name="candidate_b",
        execution_succeeded=True,
        analyses=(),
    )
    screen_b = CaseScreeningResult(
        case_name="candidate_b",
        outcome=ScreeningOutcome.FAIL,
        rules=(),
        raw_result=raw_b,
    )
    component_b = ObjectiveComponent(
        name="gain",
        measurement="gain_db",
        analysis="ac",
        direction=ObjectiveDirection.MAXIMIZE,
        status="available",
        raw_value=60.0,
        normalized_value=0.0,
        weighted_value=0.0,
        weight=1.0,
        unit="dB",
    )
    eval_b = CandidateEvaluation(
        candidate_id="candidate_b",
        state=CandidateState.INFEASIBLE,
        aggregate_score=None,
        objectives=(component_b,),
        screening_result=screen_b,
        failure_reasons=("minimum_gain",),
    )

    return CandidateEvaluationSummary(
        evaluations=(eval_b, eval_a),
        ranking=(RankedCandidate(rank=1, evaluation=eval_a),),
    )


def test_persist_writes_all_artifacts(tmp_path: Path):
    summary = make_summary()
    artifacts = CandidateEvaluationPersistence().persist(
        summary,
        tmp_path,
        workflow_result_path=tmp_path / "workflow_result.json",
    )

    assert artifacts.evaluation_json.is_file()
    assert artifacts.ranking_csv.is_file()
    assert artifacts.objective_components_csv.is_file()
    assert artifacts.optimizer_feedback_json.is_file()


def test_evaluation_json_has_schema_and_relative_workflow_link(tmp_path: Path):
    summary = make_summary()
    workflow = tmp_path / "workflow_result.json"
    artifacts = CandidateEvaluationPersistence().persist(
        summary,
        tmp_path,
        workflow_result_path=workflow,
    )

    payload = json.loads(artifacts.evaluation_json.read_text())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["artifact_root"] == "."
    assert payload["workflow_result"] == "workflow_result.json"
    assert payload["evaluation"]["valid_count"] == 1


def test_ranking_rows_are_deterministic():
    rows = ranking_rows(make_summary())

    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "candidate_a"
    assert rows[0]["aggregate_score"] == "1.2"


def test_objective_rows_sort_by_candidate_and_objective():
    rows = objective_component_rows(make_summary())

    assert [row["candidate_id"] for row in rows] == [
        "candidate_a",
        "candidate_b",
    ]


def test_csv_columns_are_stable(tmp_path: Path):
    artifacts = CandidateEvaluationPersistence().persist(
        make_summary(),
        tmp_path,
    )

    with artifacts.ranking_csv.open(newline="", encoding="utf-8") as handle:
        ranking = list(csv.DictReader(handle))
    with artifacts.objective_components_csv.open(
        newline="", encoding="utf-8"
    ) as handle:
        components = list(csv.DictReader(handle))

    assert ranking[0]["rank"] == "1"
    assert ranking[0]["state"] == "valid"
    assert components[0]["objective_name"] == "gain"


def test_optimizer_feedback_preserves_three_state_feasibility(tmp_path: Path):
    artifacts = CandidateEvaluationPersistence().persist(
        make_summary(),
        tmp_path,
    )
    payload = json.loads(artifacts.optimizer_feedback_json.read_text())
    feedback = {
        item["candidate_id"]: item
        for item in payload["feedback"]
    }

    assert feedback["candidate_a"]["feasible"] is True
    assert feedback["candidate_b"]["feasible"] is False


def test_load_payload_rejects_unknown_schema(tmp_path: Path):
    path = tmp_path / "candidate_evaluation.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "future.v99",
                "evaluation": {},
            }
        )
    )

    with pytest.raises(EvaluationPersistenceError, match="unsupported"):
        CandidateEvaluationPersistence().load_payload(path)


def test_load_payload_round_trip(tmp_path: Path):
    persistence = CandidateEvaluationPersistence()
    artifacts = persistence.persist(make_summary(), tmp_path)

    payload = persistence.load_payload(artifacts.evaluation_json)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["evaluation"]["infeasible_count"] == 1
