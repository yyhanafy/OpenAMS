"""Construction of direct-simulation manifests from assignments and plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from openams.model import Assignment, AssignmentStatus

from .errors import InvalidExecutionPlanError, InvalidSimulationManifestError
from .model import (
    SimulationBackend,
    SimulationCase,
    SimulationManifest,
    SimulationTemplate,
)


def _enum_value(value: Any) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate)


@dataclass(frozen=True, slots=True)
class DirectSimulationInput:
    """Structural bridge input; avoids importing planning or synthesis packages."""

    assignment: Assignment
    execution_plan: Any
    provenance: Mapping[str, Any] | None = None


class DirectSimulationManifestBuilder:
    """Translate direct execution plans into backend-neutral simulation cases."""

    def build(
        self,
        *,
        name: str,
        backend: SimulationBackend,
        template: SimulationTemplate,
        inputs: Sequence[DirectSimulationInput],
        analyses: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> SimulationManifest:
        analyses_tuple = tuple(analyses)
        cases = tuple(
            self._case(item, template, analyses_tuple, index)
            for index, item in enumerate(inputs)
        )
        return SimulationManifest(
            name=name,
            backend=backend,
            template=template,
            cases=cases,
            metadata={
                **dict(metadata or {}),
                "source_kind": "direct_execution_plans",
                "input_count": len(inputs),
                "case_count": len(cases),
            },
        )

    def _case(
        self,
        item: DirectSimulationInput,
        template: SimulationTemplate,
        analyses: tuple[str, ...],
        index: int,
    ) -> SimulationCase:
        assignment = item.assignment
        if assignment.status is not AssignmentStatus.SIMULATION_READY:
            raise InvalidExecutionPlanError(
                f"assignment {assignment.name!r} is not simulation-ready"
            )
        plan = item.execution_plan
        route = _enum_value(getattr(plan, "route", ""))
        if route != "direct_simulation":
            raise InvalidExecutionPlanError(
                f"assignment {assignment.name!r} uses route {route!r}, "
                "not 'direct_simulation'"
            )
        stages = tuple(_enum_value(stage) for stage in getattr(plan, "stages", ()))
        if "simulate" not in stages:
            raise InvalidExecutionPlanError(
                f"assignment {assignment.name!r} plan has no simulate stage"
            )
        if getattr(plan, "requires_executable_contract", False):
            raise InvalidExecutionPlanError(
                f"assignment {assignment.name!r} unexpectedly requires a contract"
            )

        rendered: dict[str, float] = {}
        for canonical, parameter in template.parameter_bindings.items():
            if canonical not in assignment.values:
                raise InvalidSimulationManifestError(
                    f"assignment {assignment.name!r} is missing template variable "
                    f"{canonical!r}"
                )
            value = assignment.values[canonical]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidSimulationManifestError(
                    f"assignment value {canonical!r} must be numeric"
                )
            rendered[parameter] = float(value)

        return SimulationCase(
            name=assignment.name,
            assignment=assignment,
            rendered_parameters=rendered,
            analyses=analyses,
            provenance={
                "input_index": index,
                "assignment_name": assignment.name,
                "assignment_provenance": dict(assignment.provenance),
                "plan_name": getattr(plan, "name", assignment.name),
                "plan_provenance": dict(getattr(plan, "provenance", None) or {}),
                **dict(item.provenance or {}),
            },
        )
