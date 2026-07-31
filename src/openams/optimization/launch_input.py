"""Normalized JSON input parsing for optimization launch requests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .launch_service import OptimizationLaunchRequest
from .plan_executor import RunPlanExecutionRequest
from .run_plan import SynthesisRunInput


class OptimizationLaunchInputError(ValueError):
    """Raised when normalized launch input is malformed."""


class OptimizationLaunchInputParser:
    """Parse a normalized JSON document into a typed launch request."""

    SCHEMA_VERSION = 1

    def load(
        self,
        path: str | Path,
    ) -> OptimizationLaunchRequest:
        input_path = Path(path)
        try:
            payload = json.loads(
                input_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise OptimizationLaunchInputError(
                f"failed to read launch input: {input_path}"
            ) from exc
        return self.parse(payload)

    def parse(
        self,
        payload: Mapping[str, Any],
    ) -> OptimizationLaunchRequest:
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise OptimizationLaunchInputError(
                "unsupported launch-input schema_version: "
                f"{payload.get('schema_version')!r}"
            )

        launch_id = self._required_string(
            payload,
            "launch_id",
        )
        synthesis_payload = self._required_mapping(
            payload,
            "synthesis",
        )
        execution_payload = self._required_mapping(
            payload,
            "execution",
        )

        assignments = synthesis_payload.get("assignments", [])
        if not isinstance(assignments, list):
            raise OptimizationLaunchInputError(
                "synthesis.assignments must be a list"
            )
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, Mapping):
                raise OptimizationLaunchInputError(
                    "synthesis assignment "
                    f"{index} must be an object"
                )

        unresolved_ranges = synthesis_payload.get(
            "unresolved_ranges",
            {},
        )
        if not isinstance(unresolved_ranges, Mapping):
            raise OptimizationLaunchInputError(
                "synthesis.unresolved_ranges must be an object"
            )

        normalized_ranges: dict[str, tuple[float, float]] = {}
        for name, bounds in unresolved_ranges.items():
            if isinstance(bounds, Mapping):
                try:
                    lower = float(bounds["lower"])
                    upper = float(bounds["upper"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise OptimizationLaunchInputError(
                        f"invalid range for {name!r}"
                    ) from exc
            elif (
                isinstance(bounds, (list, tuple))
                and len(bounds) == 2
            ):
                try:
                    lower = float(bounds[0])
                    upper = float(bounds[1])
                except (TypeError, ValueError) as exc:
                    raise OptimizationLaunchInputError(
                        f"invalid range for {name!r}"
                    ) from exc
            else:
                raise OptimizationLaunchInputError(
                    f"invalid range for {name!r}"
                )
            normalized_ranges[str(name)] = (lower, upper)

        fixed_parameters = synthesis_payload.get(
            "fixed_parameters",
            {},
        )
        synthesis_metadata = synthesis_payload.get(
            "metadata",
            {},
        )
        launch_metadata = payload.get("metadata", {})

        for field_name, value in (
            ("synthesis.fixed_parameters", fixed_parameters),
            ("synthesis.metadata", synthesis_metadata),
            ("metadata", launch_metadata),
        ):
            if not isinstance(value, Mapping):
                raise OptimizationLaunchInputError(
                    f"{field_name} must be an object"
                )

        session_id = self._required_string(
            execution_payload,
            "session_id",
        )
        output_directory = self._required_string(
            execution_payload,
            "output_directory",
        )

        batch_size = execution_payload.get("batch_size")
        if batch_size is not None:
            try:
                batch_size = int(batch_size)
            except (TypeError, ValueError) as exc:
                raise OptimizationLaunchInputError(
                    "execution.batch_size must be an integer"
                ) from exc

        session_metadata = execution_payload.get(
            "session_metadata",
            {},
        )
        iteration_metadata = execution_payload.get(
            "iteration_metadata",
            {},
        )
        for field_name, value in (
            ("execution.session_metadata", session_metadata),
            (
                "execution.iteration_metadata",
                iteration_metadata,
            ),
        ):
            if not isinstance(value, Mapping):
                raise OptimizationLaunchInputError(
                    f"{field_name} must be an object"
                )

        return OptimizationLaunchRequest(
            launch_id=launch_id,
            synthesis=SynthesisRunInput(
                assignments=assignments,
                unresolved_ranges=normalized_ranges,
                fixed_parameters=fixed_parameters,
                metadata=synthesis_metadata,
            ),
            execution=RunPlanExecutionRequest(
                session_id=session_id,
                output_directory=output_directory,
                batch_size=batch_size,
                session_metadata=session_metadata,
                iteration_metadata=iteration_metadata,
            ),
            metadata=launch_metadata,
        )

    @staticmethod
    def _required_mapping(
        payload: Mapping[str, Any],
        name: str,
    ) -> Mapping[str, Any]:
        value = payload.get(name)
        if not isinstance(value, Mapping):
            raise OptimizationLaunchInputError(
                f"{name} must be an object"
            )
        return value

    @staticmethod
    def _required_string(
        payload: Mapping[str, Any],
        name: str,
    ) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise OptimizationLaunchInputError(
                f"{name} must be a non-empty string"
            )
        return value
