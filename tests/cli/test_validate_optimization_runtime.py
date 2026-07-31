from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

from openams.cli import validate_optimization_runtime


def install_runtime(monkeypatch):
    module = ModuleType("preflight_project_runtime")
    module.create_workflow = lambda: object()
    module.create_objectives = lambda: ()
    monkeypatch.setitem(
        sys.modules,
        "preflight_project_runtime",
        module,
    )


def write_configs(tmp_path: Path) -> Path:
    ngspice = tmp_path / "ngspice.json"
    ngspice.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ngspice_optimization": {
                    "assignment_workflow_factory": (
                        "preflight_project_runtime:"
                        "create_workflow"
                    ),
                    "objectives_factory": (
                        "preflight_project_runtime:"
                        "create_objectives"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    composition = tmp_path / "composition.json"
    composition.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "composition": {
                    "run_plan_executor_factory": {
                        "factory": (
                            "openams.optimization.ngspice_runtime:"
                            "create_run_plan_executor"
                        ),
                        "kwargs": {
                            "config_path": "ngspice.json"
                        },
                        "path_kwargs": ["config_path"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return composition


def test_cli_writes_valid_preflight_report(
    tmp_path: Path,
    monkeypatch,
):
    install_runtime(monkeypatch)
    composition = write_configs(tmp_path)
    output = tmp_path / "preflight.json"

    assert validate_optimization_runtime.main(
        [
            "--runtime-config",
            str(composition),
            "--output",
            str(output),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "valid"
    assert payload["ngspice_runtime_path"] == str(
        (tmp_path / "ngspice.json").resolve()
    )


def test_cli_returns_two_for_invalid_runtime(
    tmp_path: Path,
):
    composition = tmp_path / "missing.json"

    assert validate_optimization_runtime.main(
        [
            "--runtime-config",
            str(composition),
        ]
    ) == 2
