import pytest

from openams.planning import (
    ExecutionRoute,
    ExecutionStage,
    PlanningRequest,
    build_execution_plan,
)


def test_fully_resolved_assignment_bypasses_contract() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="fixed_assignment",
            variables={"vbias", "w_m1"},
            resolved_values={"vbias": 0.8, "w_m1": 33.0},
        )
    )

    assert plan.route is ExecutionRoute.DIRECT_SIMULATION
    assert plan.stages == (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    )
    assert not plan.requires_executable_contract


def test_synthesis_route_does_not_build_contract() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="synthesis",
            variables={"i5", "w1", "w5"},
            synthesis_independent={"i5", "w1"},
            technology_required={"w5"},
        )
    )

    assert plan.route is ExecutionRoute.TECHNOLOGY_SYNTHESIS
    assert ExecutionStage.QUERY_TECHNOLOGY in plan.stages
    assert ExecutionStage.SYNTHESIZE_ASSIGNMENTS in plan.stages
    assert ExecutionStage.BUILD_EXECUTABLE_CONTRACT not in plan.stages
    assert not plan.requires_executable_contract


def test_optimization_route_requires_contract() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="optimization",
            variables={"vbias", "w1", "w5"},
            resolved_values={"w5": 8.0},
            optimization_independent={"vbias", "w1"},
        )
    )

    assert plan.route is ExecutionRoute.OPTIMIZATION
    assert ExecutionStage.BUILD_EXECUTABLE_CONTRACT in plan.stages
    assert plan.requires_executable_contract


def test_synthesis_then_optimization_route() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="mixed",
            variables={"i5", "w1", "w5"},
            synthesis_independent={"i5"},
            optimization_independent={"w1"},
            technology_required={"w5"},
        )
    )

    assert plan.route is ExecutionRoute.SYNTHESIS_THEN_OPTIMIZATION
    assert plan.stages == (
        ExecutionStage.VALIDATE_INPUTS,
        ExecutionStage.QUERY_TECHNOLOGY,
        ExecutionStage.SYNTHESIZE_ASSIGNMENTS,
        ExecutionStage.BUILD_EXECUTABLE_CONTRACT,
        ExecutionStage.OPTIMIZE,
        ExecutionStage.SIMULATE,
        ExecutionStage.VERIFY_SPECIFICATIONS,
    )


def test_validation_only_route() -> None:
    plan = build_execution_plan(
        PlanningRequest(
            name="validation",
            variables={"vdd"},
            resolved_values={"vdd": 1.8},
            require_simulation=False,
            require_specification_verification=False,
        )
    )

    assert plan.route is ExecutionRoute.VALIDATION_ONLY
    assert plan.stages == (ExecutionStage.VALIDATE_INPUTS,)


def test_specification_verification_requires_simulation() -> None:
    with pytest.raises(Exception, match="requires simulation"):
        build_execution_plan(
            PlanningRequest(
                name="bad",
                variables={"vdd"},
                resolved_values={"vdd": 1.8},
                require_simulation=False,
                require_specification_verification=True,
            )
        )
