from openams.planning import (
    PlanningRequest,
    VariableRole,
    build_execution_plan,
    variables_by_role,
    variables_requiring_resolution,
)


def test_plan_variable_queries() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="query",
            variables={"fixed", "free", "derived"},
            resolved_values={"fixed": 1.0},
            optimization_independent={"free"},
            dependent={"derived"},
        )
    )

    assert tuple(
        variable.name
        for variable in variables_by_role(
            plan, VariableRole.OPTIMIZATION_INDEPENDENT
        )
    ) == ("free",)

    assert tuple(
        variable.name for variable in variables_requiring_resolution(plan)
    ) == ("derived", "free")
