from __future__ import annotations

import json
from pathlib import Path

from openams.cli import launch_optimization


def test_cli_uses_repository_composition_root_by_default(
    tmp_path: Path,
    monkeypatch,
):
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "launch_id": "launch",
                "synthesis": {
                    "assignments": [{"x": 1.0}]
                },
                "execution": {
                    "session_id": "session",
                    "output_directory": str(tmp_path),
                },
            }
        ),
        encoding="utf-8",
    )
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text("{}", encoding="utf-8")

    seen = {}

    class Result:
        class Plan:
            class Route:
                value = "direct_simulation"
            route = Route()

        class Manifest:
            class Status:
                value = "completed"
            status = Status()

        plan = Plan()
        manifest = Manifest()
        manifest_json = tmp_path / "manifest.json"

    class Service:
        def launch(self, request):
            seen["request"] = request
            return Result()

    def create_service(path):
        seen["runtime"] = path
        return Service()

    monkeypatch.setattr(
        launch_optimization,
        "create_optimization_launch_service",
        create_service,
    )
    monkeypatch.setattr(
        launch_optimization,
        "OptimizationLaunchService",
        Service,
    )

    assert launch_optimization.main(
        [
            "--input",
            str(input_path),
            "--runtime-config",
            str(runtime_path),
        ]
    ) == 0

    assert seen["runtime"] == runtime_path
    assert seen["request"].launch_id == "launch"
