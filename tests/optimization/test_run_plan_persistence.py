from __future__ import annotations

import json
from pathlib import Path

import pytest

from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)
from openams.optimization.run_plan_persistence import (
    OptimizationRunPlanPersistence,
    RunPlanPersistenceError,
)


def direct_plan():
    return OptimizationRouteSelector().select(
        SynthesisRunInput(
            assignments=(
                {"vbias": 0.7, "w1": 3.0},
                {"vbias": 0.8, "w1": 4.0},
            ),
            fixed_parameters={"vdd": 1.8},
            metadata={"source": "synthesis"},
        )
    )


def search_plan():
    return OptimizationRouteSelector().select(
        SynthesisRunInput(
            unresolved_ranges={
                "vbias": (0.6, 0.9),
                "w1": (2.0, 5.0),
            },
            fixed_parameters={"vdd": 1.8},
        )
    )


def test_persist_and_load_direct_plan(tmp_path: Path):
    persistence = OptimizationRunPlanPersistence()
    artifacts = persistence.persist(
        direct_plan(),
        tmp_path,
    )

    restored = persistence.load(artifacts.run_plan_json)

    assert restored == direct_plan()
    payload = json.loads(
        artifacts.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == 1
    assert payload["artifact_type"] == "optimization_run_plan"
    assert payload["plan"]["reason_code"] == (
        "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    )


def test_persist_and_load_contract_search_plan(tmp_path: Path):
    persistence = OptimizationRunPlanPersistence()
    artifacts = persistence.persist(
        search_plan(),
        tmp_path,
    )

    restored = persistence.load(artifacts.run_plan_json)

    assert restored == search_plan()
    assert restored.requires_contract is True


def test_persist_can_include_session_link(tmp_path: Path):
    session_path = tmp_path / "session" / "optimization_session.json"
    artifacts = OptimizationRunPlanPersistence().persist(
        direct_plan(),
        tmp_path / "plan",
        session_artifact_path=session_path,
    )

    payload = json.loads(
        artifacts.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["links"]["optimization_session"] == str(
        session_path
    )


def test_link_session_artifact_updates_existing_plan(tmp_path: Path):
    persistence = OptimizationRunPlanPersistence()
    artifacts = persistence.persist(
        direct_plan(),
        tmp_path / "run",
    )
    session_path = (
        tmp_path / "run" / "session" / "optimization_session.json"
    )

    persistence.link_session_artifact(
        artifacts.run_plan_json,
        session_path,
    )

    payload = json.loads(
        artifacts.run_plan_json.read_text(encoding="utf-8")
    )
    assert payload["links"]["optimization_session"] == (
        "session/optimization_session.json"
    )
    assert (
        persistence.read_session_artifact_link(
            artifacts.run_plan_json
        )
        == session_path
    )


def test_read_session_link_returns_none_when_unlinked(tmp_path: Path):
    persistence = OptimizationRunPlanPersistence()
    artifacts = persistence.persist(
        direct_plan(),
        tmp_path,
    )

    assert persistence.read_session_artifact_link(
        artifacts.run_plan_json
    ) is None


def test_unsupported_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "optimization_run_plan.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "artifact_type": "optimization_run_plan",
                "plan": {},
                "links": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RunPlanPersistenceError,
        match="unsupported",
    ):
        OptimizationRunPlanPersistence().load(path)


def test_direct_plan_with_bounds_is_rejected_on_load(tmp_path: Path):
    persistence = OptimizationRunPlanPersistence()
    payload = persistence._payload(
        direct_plan(),
        session_artifact_path=None,
    )
    payload["plan"]["parameter_bounds"] = {
        "x": {"lower": 0.0, "upper": 1.0}
    }
    path = tmp_path / "optimization_run_plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        RunPlanPersistenceError,
        match="contains parameter bounds",
    ):
        persistence.load(path)


def test_contract_plan_without_bounds_is_rejected_on_load(
    tmp_path: Path,
):
    persistence = OptimizationRunPlanPersistence()
    payload = persistence._payload(
        search_plan(),
        session_artifact_path=None,
    )
    payload["plan"]["parameter_bounds"] = {}
    path = tmp_path / "optimization_run_plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        RunPlanPersistenceError,
        match="has no parameter bounds",
    ):
        persistence.load(path)
