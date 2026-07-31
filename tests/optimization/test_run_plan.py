from __future__ import annotations

import pytest

from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    ParameterRange,
    ResolutionState,
    RunPlanError,
    SynthesisRunInput,
)
from openams.optimization.session import OptimizationRoute


def test_fully_resolved_assignments_select_direct_simulation():
    synthesis = SynthesisRunInput(
        assignments=(
            {"vbias": 0.7, "w1": 3.0},
            {"vbias": 0.8, "w1": 4.0},
        ),
        fixed_parameters={"vdd": 1.8},
        metadata={"topology": "two_stage"},
    )

    plan = OptimizationRouteSelector().select(synthesis)

    assert plan.route is OptimizationRoute.DIRECT_SIMULATION
    assert plan.resolution_state is ResolutionState.FULLY_RESOLVED
    assert plan.reason_code == "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    assert plan.requires_contract is False
    assert plan.candidate_count == 2
    assert plan.parameter_bounds == {}
    assert plan.fixed_parameters == {"vdd": 1.8}


def test_unresolved_ranges_select_contract_search():
    synthesis = SynthesisRunInput(
        unresolved_ranges={
            "vbias": (0.6, 0.9),
            "w1": ParameterRange(2.0, 5.0),
        },
        fixed_parameters={"vdd": 1.8},
    )

    plan = OptimizationRouteSelector().select(synthesis)

    assert plan.route is OptimizationRoute.CONTRACT_SEARCH
    assert plan.resolution_state is ResolutionState.PARTIALLY_RESOLVED
    assert plan.reason_code == "UNRESOLVED_PARAMETER_RANGES_PRESENT"
    assert plan.requires_contract is True
    assert plan.parameter_bounds == {
        "vbias": (0.6, 0.9),
        "w1": (2.0, 5.0),
    }
    assert "vbias, w1" in plan.reason


def test_assignments_with_remaining_ranges_still_select_search():
    synthesis = SynthesisRunInput(
        assignments=({"w1": 3.0},),
        unresolved_ranges={"vbias": (0.6, 0.8)},
    )

    plan = OptimizationRouteSelector().select(synthesis)

    assert plan.route is OptimizationRoute.CONTRACT_SEARCH
    assert plan.resolution_state is ResolutionState.PARTIALLY_RESOLVED
    assert plan.assignments == ({"w1": 3.0},)


def test_ranges_without_assignments_or_fixed_values_are_unresolved():
    synthesis = SynthesisRunInput(
        unresolved_ranges={"x": (0.0, 1.0)}
    )

    assert synthesis.resolution_state is ResolutionState.UNRESOLVED


def test_empty_synthesis_output_is_rejected():
    with pytest.raises(
        RunPlanError,
        match="neither resolved assignments",
    ):
        OptimizationRouteSelector().select(SynthesisRunInput())


def test_invalid_parameter_ranges_are_rejected():
    with pytest.raises(ValueError, match="lower bound"):
        ParameterRange(2.0, 1.0)

    with pytest.raises(ValueError, match="finite"):
        ParameterRange(float("nan"), 1.0)


def test_degenerate_range_is_preserved_as_explicit_range():
    parameter_range = ParameterRange(0.7, 0.7)
    synthesis = SynthesisRunInput(
        unresolved_ranges={"vbias": parameter_range}
    )

    plan = OptimizationRouteSelector().select(synthesis)

    assert parameter_range.is_degenerate is True
    assert plan.route is OptimizationRoute.CONTRACT_SEARCH
    assert plan.parameter_bounds["vbias"] == (0.7, 0.7)


def test_plan_serialization_records_decision_reason():
    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(
            assignments=({"x": 1.0},),
            metadata={"source": "assignment_synthesis"},
        )
    )

    payload = plan.to_dict()

    assert payload["route"] == "direct_simulation"
    assert payload["resolution_state"] == "fully_resolved"
    assert payload["reason_code"] == "ALL_ASSIGNMENTS_FULLY_RESOLVED"
    assert payload["requires_contract"] is False
    assert payload["metadata"] == {
        "source": "assignment_synthesis"
    }
