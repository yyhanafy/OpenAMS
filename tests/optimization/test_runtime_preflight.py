from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

import pytest

from openams.optimization.preflight import (
    OptimizationRuntimePreflight,
    OptimizationRuntimePreflightError,
)


def install_project_runtime(monkeypatch):
    module = ModuleType("project_runtime")
    module.create_assignment_workflow = lambda: object()
    module.create_objectives = lambda: ()
    monkeypatch.setitem(sys.modules, "project_runtime", module)


def write_runtime_files(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    ngspice = config_dir / "ngspice.json"
    ngspice.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ngspice_optimization": {
                    "assignment_workflow_factory": (
                        "project_runtime:"
                        "create_assignment_workflow"
                    ),
                    "objectives_factory": (
                        "project_runtime:create_objectives"
                    ),
                    "proposer": "grid",
                    "points_per_dimension": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    composition = config_dir / "composition.json"
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
    return composition, ngspice


def test_preflight_validates_complete_ngspice_graph(
    tmp_path: Path,
    monkeypatch,
):
    install_project_runtime(monkeypatch)
    composition, ngspice = write_runtime_files(tmp_path)

    report = OptimizationRuntimePreflight().validate(
        composition
    )

    assert report.composition_path == composition.resolve()
    assert report.ngspice_runtime_path == ngspice.resolve()
    assert report.assignment_workflow_factory == (
        "project_runtime:create_assignment_workflow"
    )
    assert report.objectives_factory == (
        "project_runtime:create_objectives"
    )
    assert report.proposer == "grid"
    assert report.points_per_dimension == 4


def test_preflight_does_not_execute_leaf_factories(
    tmp_path: Path,
    monkeypatch,
):
    module = ModuleType("project_runtime")

    def fail_if_called():
        raise AssertionError("factory was executed")

    module.create_assignment_workflow = fail_if_called
    module.create_objectives = fail_if_called
    monkeypatch.setitem(sys.modules, "project_runtime", module)

    composition, _ = write_runtime_files(tmp_path)

    report = OptimizationRuntimePreflight().validate(
        composition
    )

    assert report.assignment_workflow_factory is not None


def test_preflight_rejects_missing_runtime_file(
    tmp_path: Path,
):
    config = tmp_path / "composition.json"
    config.write_text(
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
                            "config_path": "missing.json"
                        },
                        "path_kwargs": ["config_path"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        OptimizationRuntimePreflightError,
        match="failed to read ngspice runtime file",
    ):
        OptimizationRuntimePreflight().validate(config)


def test_preflight_rejects_unimportable_leaf_dependency(
    tmp_path: Path,
):
    composition, ngspice = write_runtime_files(tmp_path)
    payload = json.loads(ngspice.read_text(encoding="utf-8"))
    payload["ngspice_optimization"][
        "objectives_factory"
    ] = "missing_runtime:create_objectives"
    ngspice.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        OptimizationRuntimePreflightError,
        match="failed to import module",
    ):
        OptimizationRuntimePreflight().validate(composition)


def test_preflight_requires_explicit_ngspice_config_path(
    tmp_path: Path,
):
    composition = tmp_path / "composition.json"
    composition.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "composition": {
                    "run_plan_executor_factory": (
                        "openams.optimization.ngspice_runtime:"
                        "create_run_plan_executor"
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        OptimizationRuntimePreflightError,
        match="requires explicit config_path",
    ):
        OptimizationRuntimePreflight().validate(composition)
