"""Structural validation for planning requests and plans."""

from __future__ import annotations

from .errors import PlanningValidationError
from .model import (
    ExecutionPlan,
    ExecutionRoute,
    ExecutionStage,
    PlanningRequest,
    VariableRole,
)

_ALLOWED_STAGES: dict[ExecutionRoute, tuple[ExecutionStage, ...]] = {
    ExecutionRoute.DIRECT_SIMULATION: (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    ),
    ExecutionRoute.TECHNOLOGY_SYNTHESIS: (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.QUERY_TECHNOLOGY,
        ExecutionStage.SYNTHESIZE_ASSIGNMENTS,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    ),
    ExecutionRoute.OPTIMIZATION: (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.BUILD_EXECUTABLE_CONTRACT,
        ExecutionStage.OPTIMIZE,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    ),
    ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION: (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.QUERY_TECHNOLOGY,
        ExecutionStage.SYNTHESIZE_ASSIGNMENTS,
        ExecutionStage.BUILD_EXECUTABLE_CONTRACT,
        ExecutionStage.OPTIMIZE,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    ),
    ExecutionRoute.VALIDATION_ONLY: (
        ExecutionStage.VALIDATE_INPUTS,
    ),
}


def validate_planning_request(request: PlanningRequest) -> PlanningRequest:
    if not isinstance(request, PlanningRequest):
        raise TypeError("request must be a PlanningRequest")

    declared = request.variables
    role_sets = {
        VariableRole.RESOLVED: frozenset(request.resolved_values),
        VariableRole.SYNTHESIS_INDEPENDENT: request.synthesis_independent,
        VariableRole.OPTIMIZATION_INDEPENDENT: request.optimization_independent,
        VariableRole.DEPENDENT: request.dependent,
        VariableRole.TECHNOLOGY_REQUIRED: request.technology_required,
    }

    unknown = frozenset().union(*role_sets.values()) - declared
    if unknown:
        raise PlanningValidationError(
            f"classified variables are undeclared: {sorted(unknown)!r}"
        )

    roles = tuple(role_sets.items())
    for index, (left_role, left_names) in enumerate(roles):
        for right_role, right_names in roles[index + 1 :]:
            overlap = left_names & right_names
            if overlap:
                raise PlanningValidationError(
                    "variable-role conflict between "
                    f"{left_role.value!r} and {right_role.value!r}: "
                    f"{sorted(overlap)!r}"
                )

    classified = frozenset().union(*role_sets.values())
    missing = declared - classified
    if missing:
        raise PlanningValidationError(
            f"variables have no planning role: {sorted(missing)!r}"
        )

    if request.require_specification_verification and not request.require_simulation:
        raise PlanningValidationError(
            "specification verification requires simulation"
        )

    return request


def validate_execution_plan(plan: ExecutionPlan) -> ExecutionPlan:
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")

    canonical = _ALLOWED_STAGES[plan.route]
    if plan.route is ExecutionRoute.VALIDATION_ONLY:
        expected = canonical
    else:
        expected = tuple(
            stage
            for stage in canonical
            if stage is not ExecutionStage.VERIFY_SPECIFICATIONS
            or ExecutionStage.VERIFY_SPECIFICATIONS in plan.stages
        )
        if ExecutionStage.VERIFY_SPECIFICATIONS not in plan.stages:
            expected = tuple(
                stage
                for stage in canonical
                if stage is not ExecutionStage.VERIFY_SPECIFICATIONS
            )

    if plan.stages != expected:
        raise PlanningValidationError(
            f"route {plan.route.value!r} has invalid stage sequence"
        )

    optimization_route = plan.route in {
        ExecutionRoute.OPTIMIZATION,
        ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION,
    }
    if plan.requires_executable_contract != optimization_route:
        raise PlanningValidationError(
            "executable-contract flag does not match route"
        )

    return plan
