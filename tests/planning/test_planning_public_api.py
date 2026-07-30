def test_planning_public_api() -> None:
    import openams.planning as planning

    assert set(planning.__all__) == {
        "ExecutionPlan",
        "ExecutionRoute",
        "ExecutionStage",
        "PlanningError",
        "PlanningRequest",
        "PlanningValidationError",
        "VariablePlan",
        "VariableRole",
        "build_execution_plan",
        "validate_execution_plan",
        "validate_planning_request",
        "variables_by_role",
        "variables_requiring_resolution",
    }
