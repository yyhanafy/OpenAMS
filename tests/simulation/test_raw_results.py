from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openams.simulation.results import (
    AnalysisStatus,
    MeasurementDeclaration,
    MeasurementStatus,
    NgspiceRawResultParser,
    detect_ngspice_convergence,
    parse_declared_measurement,
    parse_finite_float,
)


@dataclass(frozen=True)
class FakeCaseResult:
    case_name: str
    case_directory: str
    succeeded: bool
    return_code: int | None = 0
    timed_out: bool = False


def test_parse_finite_float_accepts_scientific_notation():
    assert parse_finite_float(" -2.5e-6 ") == -2.5e-6


def test_measurement_parser_uses_last_occurrence_and_alias():
    declaration = MeasurementDeclaration(
        name="gain_db",
        aliases=("av_db",),
        analysis="ac",
        unit="dB",
    )
    result = parse_declared_measurement(
        "av_db = 50\ngain_db = 61.25\n",
        declaration,
        source_path="/tmp/log",
    )
    assert result.status is MeasurementStatus.PRESENT
    assert result.value == 61.25
    assert result.provenance["match_count"] == 2


def test_measurement_parser_marks_missing_value():
    declaration = MeasurementDeclaration(name="ugb_hz", analysis="ac")
    result = parse_declared_measurement(
        "gain_db = 60\n",
        declaration,
        source_path="/tmp/log",
    )
    assert result.status is MeasurementStatus.MISSING
    assert result.value is None


def test_measurement_parser_marks_malformed_value():
    declaration = MeasurementDeclaration(name="phase_margin_deg", analysis="ac")
    result = parse_declared_measurement(
        "phase_margin_deg = failed\n",
        declaration,
        source_path="/tmp/log",
    )
    assert result.status is MeasurementStatus.MALFORMED
    assert result.raw_text == "failed"


def test_convergence_failure_has_priority():
    converged, diagnostics = detect_ngspice_convergence(
        "Operating Point\nWarning: singular matrix\n"
    )
    assert converged is False
    assert diagnostics


def test_parser_builds_successful_analysis_result(tmp_path: Path):
    case_dir = tmp_path / "case_1"
    case_dir.mkdir()
    (case_dir / "ngspice.log").write_text(
        "Operating Point\n"
        "vout_dc = 1.25\n"
        "gain_db = 72.5\n",
        encoding="utf-8",
    )
    case = FakeCaseResult("case_1", str(case_dir), True)
    declarations = (
        MeasurementDeclaration("vout_dc", "dc", unit="V"),
        MeasurementDeclaration("gain_db", "ac", unit="dB"),
    )

    parsed = NgspiceRawResultParser().parse_case(case, declarations)

    assert parsed.execution_succeeded
    assert len(parsed.analyses) == 2
    assert all(a.status is AnalysisStatus.SUCCEEDED for a in parsed.analyses)


def test_parser_marks_analysis_incomplete_for_required_missing_measurement(
    tmp_path: Path,
):
    case_dir = tmp_path / "case_1"
    case_dir.mkdir()
    (case_dir / "ngspice.log").write_text(
        "AC Analysis\ngain_db = 70\n",
        encoding="utf-8",
    )
    case = FakeCaseResult("case_1", str(case_dir), True)
    declarations = (
        MeasurementDeclaration("gain_db", "ac"),
        MeasurementDeclaration("ugb_hz", "ac"),
    )

    parsed = NgspiceRawResultParser().parse_case(case, declarations)

    assert parsed.analyses[0].status is AnalysisStatus.INCOMPLETE
    assert parsed.analyses[0].measurements[1].status is MeasurementStatus.MISSING


def test_parser_marks_failed_execution_not_run(tmp_path: Path):
    case_dir = tmp_path / "case_1"
    case_dir.mkdir()
    (case_dir / "ngspice.log").write_text(
        "Operating Point\nvout_dc = 1.2\n",
        encoding="utf-8",
    )
    case = FakeCaseResult("case_1", str(case_dir), False, return_code=1)
    declarations = (MeasurementDeclaration("vout_dc", "dc"),)

    parsed = NgspiceRawResultParser().parse_case(case, declarations)

    assert parsed.analyses[0].status is AnalysisStatus.NOT_RUN
    assert not parsed.succeeded


def test_optional_missing_measurement_does_not_make_analysis_incomplete(
    tmp_path: Path,
):
    case_dir = tmp_path / "case_1"
    case_dir.mkdir()
    (case_dir / "ngspice.log").write_text(
        "Operating Point\nvout_dc = 1.2\n",
        encoding="utf-8",
    )
    case = FakeCaseResult("case_1", str(case_dir), True)
    declarations = (
        MeasurementDeclaration("vout_dc", "dc"),
        MeasurementDeclaration("supply_current", "dc", required=False),
    )

    parsed = NgspiceRawResultParser().parse_case(case, declarations)

    assert parsed.analyses[0].status is AnalysisStatus.SUCCEEDED
