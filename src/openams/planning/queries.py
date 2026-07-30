"""Queries over immutable execution plans."""

from __future__ import annotations

from .model import ExecutionPlan, VariablePlan, VariableRole


def variables_by_role(
    plan: ExecutionPlan,
    role: VariableRole,
) -> tuple[VariablePlan, ...]:
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")
    if not isinstance(role, VariableRole):
        raise TypeError("role must be a VariableRole")
    return tuple(variable for variable in plan.variables if variable.role is role)


def variables_requiring_resolution(
    plan: ExecutionPlan,
) -> tuple[VariablePlan, ...]:
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")
    return tuple(
        variable
        for variable in plan.variables
        if variable.role is not VariableRole.RESOLVED
    )
