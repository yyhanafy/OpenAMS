from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from openams.simulation.ngspice import (
    NgspiceAdapterError,
    NgspiceCaseStatus,
    NgspiceExecutionError,
    NgspiceInputError,
    NgspiceRunPolicy,
    NgspiceRunner,
    render_ngspice_template,
)


@dataclass(frozen=True)
class FakeTemplate:
    source: str


@dataclass(frozen=True)
class FakeCase:
    name: str
    rendered_parameters: dict[str, float]
    assignment_name: str = "assignment_000001"
    analyses: tuple[str, ...] = ("dc",)


@dataclass(frozen=True)
class FakeManifest:
    backend: str
    template: FakeTemplate
    cases: tuple[FakeCase, ...]


@dataclass(frozen=True)
class FakeRequest:
    manifest: FakeManifest
    output_directory: str


def successful_process(command, **kwargs):
    return subprocess.CompletedProcess(command, 0, "stdout-data\n", "")


def failed_process(command, **kwargs):
    return subprocess.CompletedProcess(command, 1, "", "failed\n")


def make_request(tmp_path: Path, *, cases=None) -> FakeRequest:
    template = tmp_path / "template.spice"
    template.write_text(
        ".param WIDTH={{W_M1}}\n"
        ".param CURRENT=${I_M5}\n"
        "R1 out 0 @LOAD@\n"
        ".op\n"
        ".end\n",
        encoding="utf-8",
    )
    cases = cases or (
        FakeCase(
            name="assignment_000001",
            rendered_parameters={"W_M1": 2e-6, "I_M5": 20e-6, "LOAD": 1000},
        ),
    )
    return FakeRequest(
        manifest=FakeManifest(
            backend="ngspice",
            template=FakeTemplate(str(template)),
            cases=tuple(cases),
        ),
        output_directory=str(tmp_path / "run"),
    )


def test_renderer_supports_three_explicit_token_forms():
    rendered = render_ngspice_template(
        "a={{A}} b=${B} c=@C@",
        {"A": 1.0, "B": 2, "C": "3k"},
    )
    assert rendered == "a=1.0 b=2 c=3k\n"


def test_renderer_rejects_missing_parameters():
    with pytest.raises(NgspiceInputError, match="missing parameter"):
        render_ngspice_template("x={{MISSING}}", {})


def test_runner_creates_deterministic_case_artifacts(tmp_path):
    request = make_request(tmp_path)
    runner = NgspiceRunner(
        process_runner=successful_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    result = runner.run(request)

    assert result.succeeded
    assert result.failed_case_count == 0
    case = result.cases[0]
    assert case.status is NgspiceCaseStatus.SUCCEEDED
    case_dir = Path(case.case_directory)
    assert (case_dir / "rendered.spice").is_file()
    assert (case_dir / "parameters.json").is_file()
    assert (case_dir / "case.json").is_file()
    assert (case_dir / "stdout.txt").read_text() == "stdout-data\n"
    assert (case_dir / "stderr.txt").read_text() == ""
    assert (case_dir / "result.json").is_file()
    assert (tmp_path / "run" / "run_result.json").is_file()
    deck = (case_dir / "rendered.spice").read_text()
    assert "{{" not in deck
    assert "2e-06" in deck
    assert "2e-05" in deck


def test_runner_records_nonzero_return_code_without_raising(tmp_path):
    request = make_request(tmp_path)
    runner = NgspiceRunner(
        process_runner=failed_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    result = runner.run(request)

    assert not result.succeeded
    assert result.failed_case_count == 1
    assert result.cases[0].status is NgspiceCaseStatus.FAILED
    assert result.cases[0].return_code == 1


def test_runner_records_timeout(tmp_path):
    request = make_request(tmp_path)

    def timeout_process(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial")

    runner = NgspiceRunner(
        NgspiceRunPolicy(timeout_seconds=3),
        process_runner=timeout_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    result = runner.run(request)

    assert result.cases[0].status is NgspiceCaseStatus.TIMED_OUT
    assert result.cases[0].timed_out
    assert result.cases[0].return_code is None


def test_runner_refuses_existing_case_directory_by_default(tmp_path):
    request = make_request(tmp_path)
    (tmp_path / "run" / "assignment_000001").mkdir(parents=True)
    runner = NgspiceRunner(
        process_runner=successful_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    with pytest.raises(NgspiceInputError, match="already exists"):
        runner.run(request)


def test_runner_can_overwrite_existing_case_directory(tmp_path):
    request = make_request(tmp_path)
    existing = tmp_path / "run" / "assignment_000001"
    existing.mkdir(parents=True)
    (existing / "stale.txt").write_text("stale")
    runner = NgspiceRunner(
        NgspiceRunPolicy(overwrite_existing=True),
        process_runner=successful_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    result = runner.run(request)

    assert result.succeeded
    assert not (existing / "stale.txt").exists()


def test_runner_rejects_wrong_backend(tmp_path):
    request = make_request(tmp_path)
    wrong = FakeRequest(
        manifest=FakeManifest(
            backend="mock",
            template=request.manifest.template,
            cases=request.manifest.cases,
        ),
        output_directory=request.output_directory,
    )
    runner = NgspiceRunner(
        process_runner=successful_process,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )

    with pytest.raises(NgspiceInputError, match="cannot execute backend"):
        runner.run(wrong)


def test_runner_reports_missing_executable(tmp_path):
    request = make_request(tmp_path)
    runner = NgspiceRunner(executable_resolver=lambda _: None)

    with pytest.raises(NgspiceExecutionError, match="not found"):
        runner.run(request)


def test_stop_on_failure_prevents_later_cases(tmp_path):
    cases = (
        FakeCase("case_1", {"W_M1": 1, "I_M5": 2, "LOAD": 3}),
        FakeCase("case_2", {"W_M1": 4, "I_M5": 5, "LOAD": 6}),
    )
    request = make_request(tmp_path, cases=cases)
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "bad")

    runner = NgspiceRunner(
        NgspiceRunPolicy(stop_on_failure=True),
        process_runner=fail,
        executable_resolver=lambda _: "/usr/bin/ngspice",
    )
    result = runner.run(request)

    assert len(calls) == 1
    assert len(result.cases) == 1
    assert result.metadata["requested_case_count"] == 2
