from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from openams.optimization.adapters import (
    AdapterConfigurationError,
    CandidateEvaluationEngineAdapter,
    WorkflowPersistenceAdapter,
)
from openams.optimization.evaluation import (
    CandidateEvaluationEngine,
    ObjectiveDefinition,
    ObjectiveDirection,
)


def objective():
    return ObjectiveDefinition(
        name="gain",
        measurement="gain_db",
        analysis="ac",
        direction=ObjectiveDirection.MAXIMIZE,
    )


def test_evaluation_adapter_uses_engine_owned_objectives():
    engine = CandidateEvaluationEngine([objective()])
    seen = {}

    def evaluate_many(screenings):
        seen["screenings"] = tuple(screenings)
        return "summary"

    engine.evaluate_many = evaluate_many

    adapter = CandidateEvaluationEngineAdapter(
        engine=engine,
        screening_results_getter=lambda result: result,
    )

    assert adapter.evaluate([1, 2]) == "summary"
    assert seen["screenings"] == (1, 2)


def test_evaluation_adapter_rejects_mismatched_objectives():
    engine = CandidateEvaluationEngine([objective()])
    other = ObjectiveDefinition(
        name="power",
        measurement="power_w",
        analysis="op",
        direction=ObjectiveDirection.MINIMIZE,
    )

    with pytest.raises(
        AdapterConfigurationError,
        match="must match",
    ):
        CandidateEvaluationEngineAdapter(
            engine=engine,
            objectives=[other],
            screening_results_getter=lambda result: result,
        )


@dataclass
class WorkflowArtifacts:
    workflow_json: Path


class WorkflowPersistence:
    def persist(self, result, output_directory):
        return WorkflowArtifacts(
            Path(output_directory) / "workflow_result.json"
        )


def test_workflow_persistence_accepts_repository_field_name(
    tmp_path: Path,
):
    path = WorkflowPersistenceAdapter(
        WorkflowPersistence()
    ).persist_workflow(object(), tmp_path)

    assert path == tmp_path / "workflow" / "workflow_result.json"
