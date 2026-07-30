from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from openams.simulation.results import MeasurementDeclaration
from openams.simulation.screening import (
    ComparisonOperator,
    ScreeningOutcome,
    SpecificationRule,
)
from openams.simulation.workflow import (
    SimulationWorkflow,
    WorkflowError,
    WorkflowStage,
)


@dataclass(frozen=True)
class FakeCaseExecution:
    case_name: str
    case_directory: str
    succeeded: bool = True
    return_code: int | None = 0
    timed_out: bool = False


@dataclass(frozen=True)
class FakeExecutionResult:
    cases: tuple[FakeCaseExecution, ...]

    def to_dict(self):
        return {"cases": [case.case_name for case in self.cases]}


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


def declarations():
    return (
        MeasurementDeclaration("gain_db", "ac", unit="dB"),
        MeasurementDeclaration("phase_margin_deg", "ac", unit="deg"),
    )


def rules():
    return (
        SpecificationRule(
            name="minimum_gain",
            measurement="gain_db",
            analysis="ac",
            operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
            threshold=69.5,
        ),
        SpecificationRule(
            name="minimum_phase_margin",
            measurement="phase_margin_deg",
            analysis="ac",
            operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
            threshold=60.0,
        ),
    )


def make_case(tmp_path: Path, name: str, gain: float, pm: float):
    case_dir = tmp_path / name
    case_dir.mkdir()
    (case_dir / "ngspice.log").write_text(
        "AC Analysis\n"
        f"gain_db = {gain}\n"
        f"phase_margin_deg = {pm}\n",
        encoding="utf-8",
    )
    return FakeCaseExecution(name, str(case_dir))


def test_workflow_preserves_all_intermediate_artifacts(tmp_path: Path):
    cases = (
        make_case(tmp_path, "case_pass", 72.0, 65.0),
        make_case(tmp_path, "case_fail", 60.0, 25.0),
    )
    execution = FakeExecutionResult(cases)
    runner = FakeRunner(execution)
    request = object()

    workflow = SimulationWorkflow(
        runner=runner,
        parser=__import__(
            "openams.simulation.results",
            fromlist=["NgspiceRawResultParser"],
        ).NgspiceRawResultParser(),
        declarations=declarations(),
        rules=rules(),
    )

    result = workflow.run(request)

    assert result.request is request
    assert result.execution_result is execution
    assert len(result.raw_results) == 2
    assert result.screening_summary.passed_case_count == 1
    assert result.screening_summary.failed_case_count == 1
    assert not result.succeeded


def test_workflow_rejects_rule_for_undeclared_measurement():
    with pytest.raises(ValueError, match="undeclared measurements"):
        SimulationWorkflow(
            runner=FakeRunner(FakeExecutionResult(())),
            parser=object(),
            declarations=(
                MeasurementDeclaration("gain_db", "ac"),
            ),
            rules=(
                SpecificationRule(
                    name="minimum_ugb",
                    measurement="ugb_hz",
                    analysis="ac",
                    operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                    threshold=5e6,
                ),
            ),
        )


def test_execution_failure_is_raised_as_workflow_error():
    class BrokenRunner:
        def run(self, request):
            raise RuntimeError("ngspice missing")

    workflow = SimulationWorkflow(
        runner=BrokenRunner(),
        parser=object(),
        declarations=declarations(),
        rules=rules(),
    )

    with pytest.raises(WorkflowError, match="execution failed"):
        workflow.run(object())


def test_parser_failure_is_recorded_and_other_cases_continue(tmp_path: Path):
    case1 = make_case(tmp_path, "case_1", 72.0, 65.0)
    case2 = make_case(tmp_path, "case_2", 71.0, 64.0)
    execution = FakeExecutionResult((case1, case2))
    runner = FakeRunner(execution)

    class SelectiveParser:
        def parse_case(self, case_result, declarations):
            if case_result.case_name == "case_1":
                raise ValueError("bad log")
            from openams.simulation.results import NgspiceRawResultParser
            return NgspiceRawResultParser().parse_case(case_result, declarations)

    workflow = SimulationWorkflow(
        runner=runner,
        parser=SelectiveParser(),
        declarations=declarations(),
        rules=rules(),
    )

    result = workflow.run(object())

    assert len(result.raw_results) == 1
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].stage is WorkflowStage.PARSING
    assert result.diagnostics[0].case_name == "case_1"
    assert result.screening_summary.passed_case_count == 1
    assert not result.succeeded


def test_workflow_result_to_dict_contains_every_layer(tmp_path: Path):
    case = make_case(tmp_path, "case_1", 72.0, 65.0)
    execution = FakeExecutionResult((case,))
    workflow = SimulationWorkflow(
        runner=FakeRunner(execution),
        parser=__import__(
            "openams.simulation.results",
            fromlist=["NgspiceRawResultParser"],
        ).NgspiceRawResultParser(),
        declarations=declarations(),
        rules=rules(),
    )

    result = workflow.run({"request": 1})
    payload = result.to_dict()

    assert "request" in payload
    assert "execution_result" in payload
    assert "raw_results" in payload
    assert "screening_summary" in payload
    assert payload["screening_summary"]["passed_case_count"] == 1
