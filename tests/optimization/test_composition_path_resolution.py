from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

import pytest

from openams.optimization.composition import (
    ComponentFactorySpec,
    OptimizationCompositionError,
    OptimizationCompositionRoot,
    OptimizationCompositionSpec,
)
from openams.optimization.plan_executor import (
    OptimizationRunPlanExecutor,
)


def test_declared_path_kwargs_resolve_against_config_directory(
    tmp_path: Path,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    spec = OptimizationCompositionSpec.from_mapping(
        {
            "run_plan_executor_factory": {
                "factory": "module:create_executor",
                "kwargs": {
                    "config_path": "runtime/ngspice.json",
                    "strict": True,
                },
                "path_kwargs": ["config_path"],
            }
        },
        base_directory=config_dir,
    )

    assert spec.run_plan_executor_factory.kwargs == {
        "config_path": str(
            (
                config_dir / "runtime/ngspice.json"
            ).resolve(strict=False)
        ),
        "strict": True,
    }


def test_absolute_declared_path_is_preserved(
    tmp_path: Path,
):
    runtime_path = (
        tmp_path / "runtime" / "ngspice.json"
    ).resolve(strict=False)

    spec = ComponentFactorySpec.parse(
        {
            "factory": "module:create_executor",
            "kwargs": {
                "config_path": str(runtime_path)
            },
            "path_kwargs": ["config_path"],
        },
        field_name="factory",
        base_directory=tmp_path / "different",
    )

    assert spec.kwargs["config_path"] == str(runtime_path)


def test_non_path_kwargs_are_not_modified(
    tmp_path: Path,
):
    spec = ComponentFactorySpec.parse(
        {
            "factory": "module:create_executor",
            "kwargs": {
                "label": "relative-looking/value",
                "config_path": "runtime.json",
            },
            "path_kwargs": ["config_path"],
        },
        field_name="factory",
        base_directory=tmp_path,
    )

    assert spec.kwargs["label"] == "relative-looking/value"


def test_missing_declared_path_kwarg_is_rejected():
    with pytest.raises(
        OptimizationCompositionError,
        match="references missing kwargs",
    ):
        ComponentFactorySpec.parse(
            {
                "factory": "module:create_executor",
                "kwargs": {},
                "path_kwargs": ["config_path"],
            },
            field_name="factory",
        )


def test_duplicate_declared_path_kwarg_is_rejected():
    with pytest.raises(
        OptimizationCompositionError,
        match="duplicate",
    ):
        ComponentFactorySpec.parse(
            {
                "factory": "module:create_executor",
                "kwargs": {
                    "config_path": "runtime.json"
                },
                "path_kwargs": [
                    "config_path",
                    "config_path",
                ],
            },
            field_name="factory",
        )


def test_from_file_passes_resolved_runtime_path_to_factory(
    tmp_path: Path,
    monkeypatch,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    component = object.__new__(OptimizationRunPlanExecutor)
    seen = {}

    module = ModuleType("test_relative_path_factory")

    def create_executor(config_path):
        seen["config_path"] = config_path
        return component

    module.create_executor = create_executor
    monkeypatch.setitem(
        sys.modules,
        "test_relative_path_factory",
        module,
    )

    config_path = config_dir / "composition.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "composition": {
                    "run_plan_executor_factory": {
                        "factory": (
                            "test_relative_path_factory:"
                            "create_executor"
                        ),
                        "kwargs": {
                            "config_path": (
                                "runtime/ngspice.json"
                            )
                        },
                        "path_kwargs": ["config_path"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    service = OptimizationCompositionRoot.from_file(
        config_path
    )

    assert service.executor.executor is component
    assert seen["config_path"] == str(
        (
            config_dir / "runtime/ngspice.json"
        ).resolve(strict=False)
    )
