"""Deterministic construction of immutable execution plans."""

from __future__ import annotations

from .model import (
    ExecutionPlan,
    ExecutionRoute,
    ExecutionStage,
    PlanningRequest,
    VariablePlan,
    VariableRole,
)
from .validation import validate_execution_plan, validate_planning_request


def _select_route(request: PlanningRequest) -> ExecutionRoute:
    synthesis_required = bool(
        request.synthesis_independent or request.technology_required
    )
    optimization_required = bool(request.optimization_independent)

    if synthesis_required and optimization_required:
        return ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION
    if synthesis_required:
        return ExecutionRoute.TECHNOLOGY_SYNTHESIS
    if optimization_required:
        return ExecutionRoute.OPTIMIZATION
    if request.require_simulation:
        return ExecutionRoute.DIRECT_SIMULATION
    return ExecutionRoute.VALIDATION_ONLY


def _stages_for(
    route: ExecutionRoute,
    *,
    verify_specifications: bool,
) -> tuple[ExecutionStage, ...]:
    stages: list[ExecutionStage] = [ExecutionStage.VALIDATE_INPUTS]

    if route in {
        ExecutionRoute.TECHNOLOGY_SYNTHESIS,
        ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION,
    }:
        stages.extend(
            (
                ExecutionStage.QUERY_TECHNOLOGY,
                ExecutionStage.SYNTHESIZE_ASSIGNMENTS,
            )
        )

    if route in {
        ExecutionRoute.OPTIMIZATION,
        ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION,
    }:
        stages.extend(
            (
                ExecutionStage.BUILD_EXECUTABLE_CONTRACT,
                ExecutionStage.OPTIMIZE,
            )
        )

    if route is not ExecutionRoute.VALIDATION_ONLY:
        stages.append(ExecutionStage.SIMULATE)
        if verify_specifications:
            stages.append(ExecutionStage.VERIFY_SPECIFICATIONS)

    return tuple(stages)


def _variable_plans(request: PlanningRequest) -> tuple[VariablePlan, ...]:
    result: list[VariablePlan] = []
    for name in sorted(request.variables):
        if name in request.resolved_values:
            result.append(
                VariablePlan(
                    name=name,
                    role=VariableRole.RESOLVED,
                    resolved_value=request.resolved_values[name],
                )
            )
        elif name in request.synthesis_independent:
            result.append(
                VariablePlan(
                    name=name,
                    role=VariableRole.SYNTHESIS_INDEPENDENT,
                )
            )
        elif name in request.optimization_independent:
            result.append(
                VariablePlan(
                    name=name,
                    role=VariableRole.OPTIMIZATION_INDEPENDENT,
                )
            )
        elif name in request.technology_required:
            result.append(
                VariablePlan(
                    name=name,
                    role=VariableRole.TECHNOLOGY_REQUIRED,
                )
            )
        else:
            result.append(
                VariablePlan(name=name, role=VariableRole.DEPENDENT)
            )
    return tuple(result)


def build_execution_plan(request: PlanningRequest) -> ExecutionPlan:
    """Classify the request and return the required downstream route."""

    validate_planning_request(request)
    route = _select_route(request)
    plan = ExecutionPlan(
        name=request.name,
        route=route,
        stages=_stages_for(
            route,
            verify_specifications=request.require_specification_verification,
        ),
        variables=_variable_plans(request),
        unresolved_constraints=request.unresolved_constraints,
        requires_executable_contract=route
        in {
            ExecutionRoute.OPTIMIZATION,
            ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION,
        },
        provenance=request.provenance,
    )
    return validate_execution_plan(plan)
