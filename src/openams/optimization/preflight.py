"""Preflight validation for the optimization runtime composition graph."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .composition import (
    ComponentFactorySpec,
    OptimizationCompositionError,
    OptimizationCompositionSpec,
)
from .ngspice_runtime import (
    NgspiceRuntimeConfigurationError,
    NgspiceRuntimeSpec,
)


class OptimizationRuntimePreflightError(RuntimeError):
    """Raised when runtime composition cannot be validated safely."""


@dataclass(frozen=True)
class OptimizationRuntimePreflightReport:
    """Normalized result of a non-executing runtime validation."""

    composition_path: Path
    run_plan_executor_factory: str
    run_plan_executor_kwargs: Mapping[str, Any]
    ngspice_runtime_path: Path | None
    assignment_workflow_factory: str | None
    objectives_factory: str | None
    screening_results_getter_factory: str | None
    proposer: str | None
    points_per_dimension: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "valid",
            "composition_path": str(self.composition_path),
            "run_plan_executor_factory": (
                self.run_plan_executor_factory
            ),
            "run_plan_executor_kwargs": dict(
                self.run_plan_executor_kwargs
            ),
            "ngspice_runtime_path": (
                None
                if self.ngspice_runtime_path is None
                else str(self.ngspice_runtime_path)
            ),
            "assignment_workflow_factory": (
                self.assignment_workflow_factory
            ),
            "objectives_factory": self.objectives_factory,
            "screening_results_getter_factory": (
                self.screening_results_getter_factory
            ),
            "proposer": self.proposer,
            "points_per_dimension": self.points_per_dimension,
        }


class OptimizationRuntimePreflight:
    """Validate runtime wiring without constructing or executing services."""

    def validate(
        self,
        composition_path: str | Path,
    ) -> OptimizationRuntimePreflightReport:
        path = Path(composition_path).resolve(strict=False)
        payload = self._load_json(path, "composition")

        if payload.get("schema_version") != 1:
            raise OptimizationRuntimePreflightError(
                "unsupported composition schema_version: "
                f"{payload.get('schema_version')!r}"
            )

        raw_composition = payload.get("composition")
        if not isinstance(raw_composition, Mapping):
            raise OptimizationRuntimePreflightError(
                "composition file is missing a composition object"
            )

        try:
            spec = OptimizationCompositionSpec.from_mapping(
                raw_composition,
                base_directory=path.parent,
            )
        except OptimizationCompositionError as exc:
            raise OptimizationRuntimePreflightError(str(exc)) from exc

        factory_spec = spec.run_plan_executor_factory
        factory = self._load_callable(factory_spec.factory)
        self._validate_factory_signature(factory, factory_spec)

        ngspice_path = self._ngspice_config_path(factory_spec)
        if ngspice_path is None:
            return OptimizationRuntimePreflightReport(
                composition_path=path,
                run_plan_executor_factory=factory_spec.factory,
                run_plan_executor_kwargs=dict(factory_spec.kwargs),
                ngspice_runtime_path=None,
                assignment_workflow_factory=None,
                objectives_factory=None,
                screening_results_getter_factory=None,
                proposer=None,
                points_per_dimension=None,
            )

        ngspice_spec = self._validate_ngspice_runtime(ngspice_path)

        self._load_callable(
            ngspice_spec.assignment_workflow_factory
        )
        self._load_callable(ngspice_spec.objectives_factory)
        if ngspice_spec.screening_results_getter_factory:
            self._load_callable(
                ngspice_spec.screening_results_getter_factory
            )

        return OptimizationRuntimePreflightReport(
            composition_path=path,
            run_plan_executor_factory=factory_spec.factory,
            run_plan_executor_kwargs=dict(factory_spec.kwargs),
            ngspice_runtime_path=ngspice_path,
            assignment_workflow_factory=(
                ngspice_spec.assignment_workflow_factory
            ),
            objectives_factory=ngspice_spec.objectives_factory,
            screening_results_getter_factory=(
                ngspice_spec.screening_results_getter_factory
            ),
            proposer=ngspice_spec.proposer,
            points_per_dimension=(
                ngspice_spec.points_per_dimension
            ),
        )

    @staticmethod
    def _load_json(
        path: Path,
        label: str,
    ) -> Mapping[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise OptimizationRuntimePreflightError(
                f"failed to read {label} file: {path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OptimizationRuntimePreflightError(
                f"invalid JSON in {label} file: {path}"
            ) from exc

        if not isinstance(payload, Mapping):
            raise OptimizationRuntimePreflightError(
                f"{label} file root must be an object"
            )
        return payload

    @staticmethod
    def _load_callable(reference: str) -> Callable[..., Any]:
        if ":" not in reference:
            raise OptimizationRuntimePreflightError(
                "factory reference must use module:function syntax: "
                f"{reference!r}"
            )

        module_name, function_name = reference.split(":", 1)
        if not module_name or not function_name:
            raise OptimizationRuntimePreflightError(
                "factory reference must use module:function syntax: "
                f"{reference!r}"
            )

        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise OptimizationRuntimePreflightError(
                f"failed to import module: {module_name}"
            ) from exc

        value = getattr(module, function_name, None)
        if not callable(value):
            raise OptimizationRuntimePreflightError(
                f"reference is not callable: {reference}"
            )
        return value

    @staticmethod
    def _validate_factory_signature(
        factory: Callable[..., Any],
        spec: ComponentFactorySpec,
    ) -> None:
        try:
            inspect.signature(factory).bind(
                **dict(spec.kwargs)
            )
        except TypeError as exc:
            raise OptimizationRuntimePreflightError(
                f"factory arguments are incompatible with "
                f"{spec.factory!r}: {exc}"
            ) from exc
        except (ValueError, TypeError):
            # Some extension callables do not expose inspectable signatures.
            # Import/callability validation still provides useful preflight.
            return

    @staticmethod
    def _ngspice_config_path(
        spec: ComponentFactorySpec,
    ) -> Path | None:
        if spec.factory != (
            "openams.optimization.ngspice_runtime:"
            "create_run_plan_executor"
        ):
            return None

        raw = spec.kwargs.get("config_path")
        if raw is None:
            raise OptimizationRuntimePreflightError(
                "ngspice run-plan executor requires explicit "
                "config_path for reproducible preflight"
            )
        return Path(raw).resolve(strict=False)

    def _validate_ngspice_runtime(
        self,
        path: Path,
    ) -> NgspiceRuntimeSpec:
        payload = self._load_json(path, "ngspice runtime")

        if payload.get("schema_version") != 1:
            raise OptimizationRuntimePreflightError(
                "unsupported ngspice runtime schema_version: "
                f"{payload.get('schema_version')!r}"
            )

        raw_runtime = payload.get("ngspice_optimization")
        if not isinstance(raw_runtime, Mapping):
            raise OptimizationRuntimePreflightError(
                "ngspice runtime file is missing an "
                "ngspice_optimization object"
            )

        try:
            return NgspiceRuntimeSpec.from_mapping(raw_runtime)
        except NgspiceRuntimeConfigurationError as exc:
            raise OptimizationRuntimePreflightError(str(exc)) from exc
