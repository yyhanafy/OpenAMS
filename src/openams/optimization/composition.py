"""Repository composition root for the OpenAMS optimization launch stack."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .launch_service import OptimizationLaunchService
from .persisted_plan_executor import (
    PersistedOptimizationRunPlanExecutor,
)
from .plan_executor import OptimizationRunPlanExecutor
from .run_plan_persistence import OptimizationRunPlanPersistence


class OptimizationCompositionError(RuntimeError):
    """Raised when the repository optimization stack cannot be assembled."""


@dataclass(frozen=True)
class ComponentFactorySpec:
    """Reference and keyword arguments for an infrastructure factory.

    ``path_kwargs`` identifies keyword arguments whose relative string values
    must be resolved against the composition file directory.
    """

    factory: str
    kwargs: Mapping[str, Any]
    path_kwargs: tuple[str, ...] = ()

    @classmethod
    def parse(
        cls,
        value: str | Mapping[str, Any],
        *,
        field_name: str,
        base_directory: str | Path | None = None,
    ) -> "ComponentFactorySpec":
        if isinstance(value, str):
            if not value:
                raise OptimizationCompositionError(
                    f"{field_name} must be a non-empty string"
                )
            return cls(factory=value, kwargs={}, path_kwargs=())

        if not isinstance(value, Mapping):
            raise OptimizationCompositionError(
                f"{field_name} must be a string or object"
            )

        factory = value.get("factory")
        if not isinstance(factory, str) or not factory:
            raise OptimizationCompositionError(
                f"{field_name}.factory must be a non-empty string"
            )

        kwargs = value.get("kwargs", {})
        if not isinstance(kwargs, Mapping):
            raise OptimizationCompositionError(
                f"{field_name}.kwargs must be an object"
            )

        path_kwargs = value.get("path_kwargs", ())
        if not isinstance(path_kwargs, Sequence) or isinstance(
            path_kwargs,
            (str, bytes),
        ):
            raise OptimizationCompositionError(
                f"{field_name}.path_kwargs must be a list of strings"
            )

        normalized_path_kwargs: list[str] = []
        for index, name in enumerate(path_kwargs):
            if not isinstance(name, str) or not name:
                raise OptimizationCompositionError(
                    f"{field_name}.path_kwargs[{index}] must be "
                    "a non-empty string"
                )
            if name in normalized_path_kwargs:
                raise OptimizationCompositionError(
                    f"{field_name}.path_kwargs contains duplicate "
                    f"entry {name!r}"
                )
            normalized_path_kwargs.append(name)

        unknown = [
            name
            for name in normalized_path_kwargs
            if name not in kwargs
        ]
        if unknown:
            raise OptimizationCompositionError(
                f"{field_name}.path_kwargs references missing kwargs: "
                + ", ".join(sorted(unknown))
            )

        resolved_kwargs = dict(kwargs)
        if base_directory is not None:
            base = Path(base_directory)
            for name in normalized_path_kwargs:
                raw_value = resolved_kwargs[name]
                if not isinstance(raw_value, (str, os.PathLike)):
                    raise OptimizationCompositionError(
                        f"{field_name}.kwargs.{name} must be a path string"
                    )
                candidate = Path(raw_value)
                if not candidate.is_absolute():
                    candidate = base / candidate
                resolved_kwargs[name] = str(candidate.resolve(strict=False))

        return cls(
            factory=factory,
            kwargs=resolved_kwargs,
            path_kwargs=tuple(normalized_path_kwargs),
        )


@dataclass(frozen=True)
class OptimizationRuntimeComponents:
    """Concrete leaf components required by the repository composition root."""

    run_plan_executor: OptimizationRunPlanExecutor


@dataclass(frozen=True)
class OptimizationCompositionSpec:
    """Normalized composition specification."""

    run_plan_executor_factory: ComponentFactorySpec
    plan_subdirectory: str = "plan"
    require_session_artifact: bool = True

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_directory: str | Path | None = None,
    ) -> "OptimizationCompositionSpec":
        if "run_plan_executor_factory" not in payload:
            raise OptimizationCompositionError(
                "run_plan_executor_factory is required"
            )

        reference = ComponentFactorySpec.parse(
            payload["run_plan_executor_factory"],
            field_name="run_plan_executor_factory",
            base_directory=base_directory,
        )

        plan_subdirectory = payload.get(
            "plan_subdirectory",
            "plan",
        )
        if not isinstance(plan_subdirectory, str) or not plan_subdirectory:
            raise OptimizationCompositionError(
                "plan_subdirectory must be a non-empty string"
            )

        require_session_artifact = payload.get(
            "require_session_artifact",
            True,
        )
        if not isinstance(require_session_artifact, bool):
            raise OptimizationCompositionError(
                "require_session_artifact must be a boolean"
            )

        return cls(
            run_plan_executor_factory=reference,
            plan_subdirectory=plan_subdirectory,
            require_session_artifact=require_session_artifact,
        )


class OptimizationCompositionRoot:
    """Assemble repository-owned optimization application layers."""

    def build(
        self,
        spec: OptimizationCompositionSpec,
    ) -> OptimizationLaunchService:
        run_plan_executor = self._load_component(
            spec.run_plan_executor_factory,
            expected_type=OptimizationRunPlanExecutor,
        )

        persisted_executor = PersistedOptimizationRunPlanExecutor(
            executor=run_plan_executor,
            persistence=OptimizationRunPlanPersistence(),
            plan_subdirectory=spec.plan_subdirectory,
            require_session_artifact=(
                spec.require_session_artifact
            ),
        )

        return OptimizationLaunchService(
            executor=persisted_executor,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
    ) -> OptimizationLaunchService:
        config_path = Path(path).resolve(strict=False)
        try:
            payload = json.loads(
                config_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise OptimizationCompositionError(
                f"failed to read optimization runtime config: "
                f"{config_path}"
            ) from exc

        if payload.get("schema_version") != 1:
            raise OptimizationCompositionError(
                "unsupported optimization runtime schema_version: "
                f"{payload.get('schema_version')!r}"
            )

        composition = payload.get("composition")
        if not isinstance(composition, Mapping):
            raise OptimizationCompositionError(
                "runtime config is missing a composition object"
            )

        return cls().build(
            OptimizationCompositionSpec.from_mapping(
                composition,
                base_directory=config_path.parent,
            )
        )

    @staticmethod
    def _load_component(
        spec: ComponentFactorySpec,
        *,
        expected_type: type,
    ) -> Any:
        factory = OptimizationCompositionRoot._load_callable(
            spec.factory
        )
        try:
            component = factory(**dict(spec.kwargs))
        except TypeError as exc:
            raise OptimizationCompositionError(
                f"failed to invoke factory {spec.factory!r} "
                f"with configured keyword arguments"
            ) from exc

        if not isinstance(component, expected_type):
            raise OptimizationCompositionError(
                f"factory {spec.factory!r} returned "
                f"{type(component).__name__}, expected "
                f"{expected_type.__name__}"
            )
        return component

    @staticmethod
    def _load_callable(
        reference: str,
    ) -> Callable[..., Any]:
        if ":" not in reference:
            raise OptimizationCompositionError(
                "component factory must use module:function syntax"
            )

        module_name, function_name = reference.split(":", 1)
        if not module_name or not function_name:
            raise OptimizationCompositionError(
                "component factory must use module:function syntax"
            )

        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise OptimizationCompositionError(
                f"failed to import component module: {module_name}"
            ) from exc

        factory = getattr(module, function_name, None)
        if not callable(factory):
            raise OptimizationCompositionError(
                f"component factory is not callable: {reference}"
            )
        return factory


DEFAULT_RUNTIME_CONFIG_ENV = "OPENAMS_OPTIMIZATION_RUNTIME_CONFIG"


def create_optimization_launch_service(
    config_path: str | Path | None = None,
) -> OptimizationLaunchService:
    """Build the launch service through the repository composition root."""

    resolved = config_path
    if resolved is None:
        resolved = os.environ.get(DEFAULT_RUNTIME_CONFIG_ENV)

    if resolved is None or str(resolved) == "":
        raise OptimizationCompositionError(
            "optimization runtime config is required; pass config_path "
            f"or set {DEFAULT_RUNTIME_CONFIG_ENV}"
        )

    return OptimizationCompositionRoot.from_file(resolved)
