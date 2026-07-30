from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

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
    ScreeningSummary,
)
from openams.simulation.persistence import (
    PersistenceError,
    SCHEMA_VERSION,
    SimulationWorkflowPersistence,
    deterministic_summary_rows,
)
from openams.simulation.workflow import SimulationWorkflowResult


def make_result(tmp_path: Path) -> SimulationWorkflowResult:
    case_dir = tmp_path / "runs" / "case_1"
    measurement = ScalarMeasurement(
        name="gain_db",
        analysis="ac",
        status=MeasurementStatus.PRESENT,
        value=72.5,
        unit="dB",
        source="log",
        provenance={"source_path": str(case_dir / "ngspice.log")},
    )
    raw = RawSimulationCaseResult(
        case_name="case_1",
        execution_succeeded=True,
        analyses=(
            RawAnalysisResult(
                analysis="ac",
                status=AnalysisStatus.SUCCEEDED,
                converged=True,
                measurements=(measurement,),
                provenance={"case_directory": str(case_dir)},
            ),
        ),
        provenance={"case_directory": str(case_dir)},
    )
    rule = RuleScreeningResult(
        rule_name="minimum_gain",
        measurement="gain_db",
        analysis="ac",
        outcome=ScreeningOutcome.PASS,
        actual_value=72.5,
        expected={
            "operator": ">=",
            "threshold": 69.5,
            "tolerance": 0.0,
        },
        unit="dB",
        measurement_status="present",
    )
    case = CaseScreeningResult(
        case_name="case_1",
        outcome=ScreeningOutcome.PASS,
        rules=(rule,),
        raw_result=raw,
    )
    summary = ScreeningSummary(cases=(case,))

    class Request:
        def to_dict(self):
            return {"output_directory": str(tmp_path)}

    class Execution:
        def to_dict(self):
            return {
                "cases": [
                    {
                        "case_name": "case_1",
                        "case_directory": str(case_dir),
                    }
                ]
            }

    return SimulationWorkflowResult(
        request=Request(),
        execution_result=Execution(),
        raw_results=(raw,),
        screening_summary=summary,
    )


def test_persist_writes_versioned_json_and_csv(tmp_path: Path):
    result = make_result(tmp_path)
    artifacts = SimulationWorkflowPersistence().persist(result, tmp_path)

    assert artifacts.workflow_json.is_file()
    assert artifacts.summary_csv.is_file()

    payload = json.loads(artifacts.workflow_json.read_text())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["artifact_root"] == "."
    assert payload["workflow"]["succeeded"] is True


def test_paths_under_output_directory_are_relative(tmp_path: Path):
    result = make_result(tmp_path)
    artifacts = SimulationWorkflowPersistence().persist(result, tmp_path)
    text = artifacts.workflow_json.read_text()

    assert str(tmp_path) not in text
    assert "runs/case_1" in text


def test_summary_rows_are_deterministic():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        result = make_result(Path(directory))
        rows = deterministic_summary_rows(result)

    assert len(rows) == 1
    assert rows[0]["case_name"] == "case_1"
    assert rows[0]["rule_name"] == "minimum_gain"
    assert rows[0]["actual_value"] == "72.5"


def test_summary_csv_has_stable_columns(tmp_path: Path):
    result = make_result(tmp_path)
    artifacts = SimulationWorkflowPersistence().persist(result, tmp_path)

    with artifacts.summary_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["case_outcome"] == "pass"
    assert rows[0]["operator"] == ">="
    assert rows[0]["threshold"] == "69.5"


def test_load_payload_rejects_unknown_schema(tmp_path: Path):
    path = tmp_path / "workflow_result.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "future.v99",
                "workflow": {},
            }
        )
    )

    with pytest.raises(PersistenceError, match="unsupported"):
        SimulationWorkflowPersistence().load_payload(path)


def test_load_payload_round_trip(tmp_path: Path):
    result = make_result(tmp_path)
    persistence = SimulationWorkflowPersistence()
    artifacts = persistence.persist(result, tmp_path)

    payload = persistence.load_payload(artifacts.workflow_json)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["workflow"]["screening_summary"]["passed_case_count"] == 1
