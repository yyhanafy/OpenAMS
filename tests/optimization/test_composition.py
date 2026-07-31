from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import sys

import pytest

from openams.optimization.composition import (
    DEFAULT_RUNTIME_CONFIG_ENV,
    ComponentFactorySpec,
    OptimizationCompositionError,
    OptimizationCompositionRoot,
    OptimizationCompositionSpec,
    create_optimization_launch_service,
)
from openams.optimization.launch_service import (
    OptimizationLaunchService,
)
from openams.optimization.plan_executor import (
    OptimizationRunPlanExecutor,
)


def install_component_module(monkeypatch, component):
    module = ModuleType("test_runtime_components")
    module.create_run_plan_executor = lambda **kwargs: component
    monkeypatch.setitem(
        sys.modules,
        "test_runtime_components",
        module,
    )


def factory_spec(**kwargs):
    return ComponentFactorySpec(
        factory=(
            "test_runtime_components:"
            "create_run_plan_executor"
        ),
        kwargs=kwargs,
    )


def test_composition_root_builds_launch_service(
    monkeypatch,
):
    component = object.__new__(OptimizationRunPlanExecutor)
    install_component_module(monkeypatch, component)

    service = OptimizationCompositionRoot().build(
        OptimizationCompositionSpec(
            run_plan_executor_factory=factory_spec(),
            plan_subdirectory="route",
            require_session_artifact=False,
        )
    )

    assert isinstance(service, OptimizationLaunchService)
    assert service.executor.executor is component
    assert service.executor.plan_subdirectory == "route"
    assert service.executor.require_session_artifact is False


def test_component_factory_receives_configured_kwargs(
    monkeypatch,
):
    component = object.__new__(OptimizationRunPlanExecutor)
    seen = {}

    module = ModuleType("test_runtime_components")

    def create_run_plan_executor(**kwargs):
        seen.update(kwargs)
        return component

    module.create_run_plan_executor = create_run_plan_executor
    monkeypatch.setitem(
        sys.modules,
        "test_runtime_components",
        module,
    )

    service = OptimizationCompositionRoot().build(
        OptimizationCompositionSpec(
            run_plan_executor_factory=factory_spec(
                config_path="ngspice_runtime.json",
                strict=True,
            )
        )
    )

    assert isinstance(service, OptimizationLaunchService)
    assert seen == {
        "config_path": "ngspice_runtime.json",
        "strict": True,
    }


def test_legacy_string_factory_form_is_supported():
    spec = OptimizationCompositionSpec.from_mapping(
        {
            "run_plan_executor_factory": (
                "module:create_executor"
            )
        }
    )

    assert spec.run_plan_executor_factory.factory == (
        "module:create_executor"
    )
    assert spec.run_plan_executor_factory.kwargs == {}


def test_object_factory_form_is_supported():
    spec = OptimizationCompositionSpec.from_mapping(
        {
            "run_plan_executor_factory": {
                "factory": "module:create_executor",
                "kwargs": {
                    "config_path": "runtime.json"
                },
            }
        }
    )

    assert spec.run_plan_executor_factory.factory == (
        "module:create_executor"
    )
    assert spec.run_plan_executor_factory.kwargs == {
        "config_path": "runtime.json"
    }


def test_wrong_component_type_is_rejected(monkeypatch):
    install_component_module(monkeypatch, object())

    with pytest.raises(
        OptimizationCompositionError,
        match="expected OptimizationRunPlanExecutor",
    ):
        OptimizationCompositionRoot().build(
            OptimizationCompositionSpec(
                run_plan_executor_factory=factory_spec()
            )
        )


def test_invalid_factory_kwargs_are_rejected():
    with pytest.raises(
        OptimizationCompositionError,
        match="kwargs must be an object",
    ):
        OptimizationCompositionSpec.from_mapping(
            {
                "run_plan_executor_factory": {
                    "factory": "module:create_executor",
                    "kwargs": [],
                }
            }
        )


def test_create_service_reads_runtime_config(
    tmp_path: Path,
    monkeypatch,
):
    component = object.__new__(OptimizationRunPlanExecutor)
    install_component_module(monkeypatch, component)

    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "composition": {
                    "run_plan_executor_factory": (
                        "test_runtime_components:"
                        "create_run_plan_executor"
                    ),
                    "require_session_artifact": False,
                },
            }
        ),
        encoding="utf-8",
    )

    service = create_optimization_launch_service(config)

    assert isinstance(service, OptimizationLaunchService)


def test_environment_runtime_config_is_supported(
    tmp_path: Path,
    monkeypatch,
):
    component = object.__new__(OptimizationRunPlanExecutor)
    install_component_module(monkeypatch, component)

    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "composition": {
                    "run_plan_executor_factory": (
                        "test_runtime_components:"
                        "create_run_plan_executor"
                    ),
                    "require_session_artifact": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        DEFAULT_RUNTIME_CONFIG_ENV,
        str(config),
    )

    service = create_optimization_launch_service()

    assert isinstance(service, OptimizationLaunchService)


def test_missing_runtime_config_is_rejected(monkeypatch):
    monkeypatch.delenv(
        DEFAULT_RUNTIME_CONFIG_ENV,
        raising=False,
    )

    with pytest.raises(
        OptimizationCompositionError,
        match="runtime config is required",
    ):
        create_optimization_launch_service()
