from __future__ import annotations

from pathlib import Path
from types import ModuleType
import sys

from openams.optimization.composition import (
    OptimizationCompositionRoot,
    OptimizationCompositionSpec,
)
from openams.optimization.plan_executor import (
    OptimizationRunPlanExecutor,
)


def test_composition_passes_ngspice_config_path(
    monkeypatch,
):
    component = object.__new__(OptimizationRunPlanExecutor)
    seen = {}

    module = ModuleType("test_ngspice_bridge")

    def create_run_plan_executor(config_path=None):
        seen["config_path"] = config_path
        return component

    module.create_run_plan_executor = create_run_plan_executor
    monkeypatch.setitem(
        sys.modules,
        "test_ngspice_bridge",
        module,
    )

    service = OptimizationCompositionRoot().build(
        OptimizationCompositionSpec.from_mapping(
            {
                "run_plan_executor_factory": {
                    "factory": (
                        "test_ngspice_bridge:"
                        "create_run_plan_executor"
                    ),
                    "kwargs": {
                        "config_path": (
                            "config/ngspice_optimization.json"
                        )
                    },
                }
            }
        )
    )

    assert service.executor.executor is component
    assert seen["config_path"] == (
        "config/ngspice_optimization.json"
    )
