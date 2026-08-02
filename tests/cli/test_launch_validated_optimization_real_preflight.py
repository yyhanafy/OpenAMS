from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

from openams.cli import launch_validated_optimization


def test_real_preflight_then_delegated_launch(
    tmp_path: Path,
    monkeypatch,
):
    project_runtime = ModuleType(
        "validated_launch_project_runtime"
    )
    project_runtime.create_workflow = lambda: object()
    project_runtime.create_objectives = lambda: ()
    monkeypatch.setitem(
        sys.modules,
        "validated_launch_project_runtime",
        project_runtime,
    )

    ngspice = tmp_path / "ngspice.json"
    ngspice.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ngspice_optimization": {
                    "assignment_workflow_factory": (
                        "validated_launch_project_runtime:"
                        "create_workflow"
                    ),
                    "objectives_factory": (
                        "validated_launch_project_runtime:"
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

    seen = {}

    def fake_launch(argv):
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(
        launch_validated_optimization.launch_optimization,
        "main",
        fake_launch,
    )

    result = launch_validated_optimization.main(
        [
            "--runtime-config",
            str(composition),
            "--input",
            "launch.json",
        ]
    )

    assert result == 0
    assert seen["argv"] == [
        "--runtime-config",
        str(composition),
        "--input",
        "launch.json",
    ]
