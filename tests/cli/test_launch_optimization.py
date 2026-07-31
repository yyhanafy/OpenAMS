from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

import pytest

from openams.cli.launch_optimization import (
    OptimizationLaunchCliError,
    _load_factory,
    main,
)
from openams.optimization.launch_manifest import (
    OptimizationLaunchArtifacts,
    OptimizationLaunchManifest,
    OptimizationLaunchManifestArtifacts,
    OptimizationLaunchStatus,
)
from openams.optimization.launch_service import (
    OptimizationLaunchResult,
    OptimizationLaunchService,
)
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)


def input_payload(tmp_path: Path):
    return {
        "schema_version": 1,
        "launch_id": "launch",
        "synthesis": {
            "assignments": [{"x": 1.0}],
        },
        "execution": {
            "session_id": "session",
            "output_directory": str(tmp_path),
        },
    }


def test_factory_reference_requires_colon():
    with pytest.raises(
        OptimizationLaunchCliError,
        match="module:function",
    ):
        _load_factory("missing_separator")


def test_cli_prints_only_route_status_and_manifest(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(input_payload(tmp_path)),
        encoding="utf-8",
    )
    manifest_path = (
        tmp_path / "optimization_launch_manifest.json"
    )
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(assignments=({"x": 1.0},))
    )
    manifest = OptimizationLaunchManifest(
        launch_id="launch",
        status=OptimizationLaunchStatus.COMPLETED,
        route=plan.route.value,
        reason_code=plan.reason_code,
        artifacts=OptimizationLaunchArtifacts(
            run_plan=tmp_path / "plan.json"
        ),
    )

    class FakeService(OptimizationLaunchService):
        def __init__(self):
            pass

        def launch(self, request):
            return OptimizationLaunchResult(
                plan=plan,
                execution=object(),
                manifest=manifest,
                manifest_artifacts=(
                    OptimizationLaunchManifestArtifacts(
                        manifest_json=manifest_path
                    )
                ),
            )

    module = ModuleType("test_launch_factory")
    module.create_service = lambda: FakeService()
    monkeypatch.setitem(
        sys.modules,
        "test_launch_factory",
        module,
    )

    assert main(
        [
            "--input",
            str(input_path),
            "--factory",
            "test_launch_factory:create_service",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "manifest": str(manifest_path),
        "route": "direct_simulation",
        "status": "completed",
    }
