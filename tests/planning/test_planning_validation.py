import pytest

from openams.planning import (
    PlanningRequest,
    PlanningValidationError,
    validate_planning_request,
)


def test_all_variables_require_exactly_one_role() -> None:
    with pytest.raises(PlanningValidationError, match="no planning role"):
        validate_planning_request(
            PlanningRequest(
                name="missing",
                variables={"x", "y"},
                resolved_values={"x": 1.0},
            )
        )


def test_role_overlap_is_rejected() -> None:
    with pytest.raises(PlanningValidationError, match="role conflict"):
        validate_planning_request(
            PlanningRequest(
                name="overlap",
                variables={"x"},
                synthesis_independent={"x"},
                optimization_independent={"x"},
            )
        )


def test_undeclared_classified_variable_is_rejected() -> None:
    with pytest.raises(PlanningValidationError, match="undeclared"):
        validate_planning_request(
            PlanningRequest(
                name="unknown",
                variables={"x"},
                resolved_values={"x": 1.0, "y": 2.0},
            )
        )
