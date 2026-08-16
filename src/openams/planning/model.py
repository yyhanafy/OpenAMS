"""Immutable planning intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ._immutable import (
    freeze_mapping,
    freeze_names,
    freeze_numeric_mapping,
    require_name,
)


class VariableRole(str, Enum):
    RESOLVED = "resolved"
    SYNTHESIS_INDEPENDENT = "synthesis_independent"
    OPTIMIZATION_INDEPENDENT = "optimization_independent"
    DEPENDENT = "dependent"
    TECHNOLOGY_REQUIRED = "technology_required"


class ExecutionRoute(str, Enum):
    DIRECT_SIMULATION = "direct_simulation"
    TECHNOLOGY_SYNTHESIS = "technology_synthesis"
    OPTIMIZATION = "optimization"
    SYNTHESIS_THEN_OPTIMIZATION = "synthesis_then_optimization"
    VALIDATION_ONLY = "validation_only"


class ExecutionStage(str, Enum):
    VALIDATE_INPUTS = "validate_inputs"
    QUERY_TECHNOLOGY = "query_technology"
    SYNTHESIZE_ASSIGNMENTS = "synthesize_assignments"
    BUILD_EXECUTABLE_CONTRACT = "build_executable_contract"
    OPTIMIZE = "optimize"
    SIMULATE = "simulate"
    VERIFY_SPECIFICATIONS = "verify_specifications"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanningRequest:
    name: str
    variables: frozenset[str]
    resolved_values: Mapping[str, float] = field(default_factory=dict)
    synthesis_independent: frozenset[str] = field(default_factory=frozenset)
    optimization_independent: frozenset[str] = field(default_factory=frozenset)
    dependent: frozenset[str] = field(default_factory=frozenset)
    technology_required: frozenset[str] = field(default_factory=frozenset)
    unresolved_constraints: frozenset[str] = field(default_factory=frozenset)
    require_simulation: bool = True
    require_specification_verification: bool = True
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "planning request name"))
        object.__setattr__(
            self, "variables", freeze_names(self.variables, "variables")
        )
        object.__setattr__(
            self,
            "resolved_values",
            freeze_numeric_mapping(self.resolved_values, "resolved_values"),
        )
        object.__setattr__(
            self,
            "synthesis_independent",
            freeze_names(self.synthesis_independent, "synthesis_independent"),
        )
        object.__setattr__(
            self,
            "optimization_independent",
            freeze_names(
                self.optimization_independent, "optimization_independent"
            ),
        )
        object.__setattr__(
            self, "dependent", freeze_names(self.dependent, "dependent")
        )
        object.__setattr__(
            self,
            "technology_required",
            freeze_names(self.technology_required, "technology_required"),
        )
        object.__setattr__(
            self,
            "unresolved_constraints",
            freeze_names(self.unresolved_constraints, "unresolved_constraints"),
        )
        if not isinstance(self.require_simulation, bool):
            raise TypeError("require_simulation must be boolean")
        if not isinstance(self.require_specification_verification, bool):
            raise TypeError("require_specification_verification must be boolean")
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))


@dataclass(frozen=True, slots=True, kw_only=True)
class VariablePlan:
    name: str
    role: VariableRole
    resolved_value: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "variable name"))
        if not isinstance(self.role, VariableRole):
            raise TypeError("role must be a VariableRole")
        if self.role is VariableRole.RESOLVED:
            if self.resolved_value is None:
                raise ValueError("resolved variable requires resolved_value")
        elif self.resolved_value is not None:
            raise ValueError("unresolved variable must not have resolved_value")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPlan:
    name: str
    route: ExecutionRoute
    stages: tuple[ExecutionStage, ...]
    variables: tuple[VariablePlan, ...]
    unresolved_constraints: frozenset[str] = field(default_factory=frozenset)
    requires_executable_contract: bool = False
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "execution plan name"))
        if not isinstance(self.route, ExecutionRoute):
            raise TypeError("route must be an ExecutionRoute")

        stages = tuple(self.stages)
        if not stages:
            raise ValueError("execution plan requires at least one stage")
        for stage in stages:
            if not isinstance(stage, ExecutionStage):
                raise TypeError("stages must contain ExecutionStage values")
        if len(set(stages)) != len(stages):
            raise ValueError("execution stages must not repeat")

        variables = tuple(self.variables)
        names: set[str] = set()
        for variable in variables:
            if not isinstance(variable, VariablePlan):
                raise TypeError("variables must contain VariablePlan values")
            key = variable.name.lower()
            if key in names:
                raise ValueError(f"duplicate planned variable {variable.name!r}")
            names.add(key)

        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "variables", variables)
        object.__setattr__(
            self,
            "unresolved_constraints",
            freeze_names(self.unresolved_constraints, "unresolved_constraints"),
        )
        if not isinstance(self.requires_executable_contract, bool):
            raise TypeError("requires_executable_contract must be boolean")
        object.__setattr__(self, "provenance", freeze_mapping(self.provenance))
