from types import MappingProxyType

import pytest

from openams.planning import (
    ExecutionPlan,
    ExecutionRoute,
    ExecutionStage,
    PlanningRequest,
    VariablePlan,
    VariableRole,
)


def test_planning_request_is_immutable_and_normalized() -> None:
    request = PlanningRequest(
        name="two_stage",
        variables={"vbias", "w_m1"},
        resolved_values={"vbias": 0.8},
        dependent={"w_m1"},
        provenance={"source": "metadata"},
    )

    assert request.variables == frozenset({"vbias", "w_m1"})
    assert request.resolved_values["vbias"] == 0.8
    assert isinstance(request.resolved_values, MappingProxyType)
    assert isinstance(request.provenance, MappingProxyType)


def test_variable_plan_enforces_resolved_value_policy() -> None:
    with pytest.raises(ValueError, match="requires"):
        VariablePlan(name="x", role=VariableRole.RESOLVED)
    with pytest.raises(ValueError, match="must not"):
        VariablePlan(
            name="x",
            role=VariableRole.DEPENDENT,
            resolved_value=1.0,
        )


def test_execution_plan_rejects_repeated_stages() -> None:
    with pytest.raises(ValueError, match="repeat"):
        ExecutionPlan(
            name="bad",
            route=ExecutionRoute.VALIDATION_ONLY,
            stages=(
                ExecutionStage.VALIDATE_INPUTS,
                ExecutionStage.VALIDATE_INPUTS,
            ),
            variables=(),
        )
