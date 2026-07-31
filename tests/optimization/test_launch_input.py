from __future__ import annotations

import pytest

from openams.optimization.launch_input import (
    OptimizationLaunchInputError,
    OptimizationLaunchInputParser,
)
from openams.optimization.run_plan import ResolutionState


def payload():
    return {
        "schema_version": 1,
        "launch_id": "launch_0001",
        "synthesis": {
            "assignments": [{"x": 1.0}],
            "unresolved_ranges": {},
            "fixed_parameters": {"vdd": 1.8},
            "metadata": {"source": "synthesis"},
        },
        "execution": {
            "session_id": "session_0001",
            "output_directory": "runtime/launch_0001",
            "batch_size": 4,
            "session_metadata": {"topology": "two_stage"},
            "iteration_metadata": {"seed": 7},
        },
        "metadata": {"command": "launch"},
    }


def test_parse_normalized_launch_input():
    request = OptimizationLaunchInputParser().parse(payload())

    assert request.launch_id == "launch_0001"
    assert request.synthesis.resolution_state is (
        ResolutionState.FULLY_RESOLVED
    )
    assert request.synthesis.assignments == ({"x": 1.0},)
    assert request.synthesis.fixed_parameters == {"vdd": 1.8}
    assert request.execution.session_id == "session_0001"
    assert str(request.execution.output_directory) == (
        "runtime/launch_0001"
    )
    assert request.execution.batch_size == 4
    assert request.metadata == {"command": "launch"}


def test_object_and_pair_range_forms_are_supported():
    source = payload()
    source["synthesis"]["assignments"] = []
    source["synthesis"]["unresolved_ranges"] = {
        "x": {"lower": 0.0, "upper": 1.0},
        "y": [2.0, 3.0],
    }

    request = OptimizationLaunchInputParser().parse(source)

    assert request.synthesis.unresolved_ranges["x"].to_tuple() == (
        0.0,
        1.0,
    )
    assert request.synthesis.unresolved_ranges["y"].to_tuple() == (
        2.0,
        3.0,
    )


def test_unsupported_schema_is_rejected():
    source = payload()
    source["schema_version"] = 99

    with pytest.raises(
        OptimizationLaunchInputError,
        match="unsupported",
    ):
        OptimizationLaunchInputParser().parse(source)


def test_missing_output_directory_is_rejected():
    source = payload()
    del source["execution"]["output_directory"]

    with pytest.raises(
        OptimizationLaunchInputError,
        match="output_directory",
    ):
        OptimizationLaunchInputParser().parse(source)


def test_invalid_assignment_shape_is_rejected():
    source = payload()
    source["synthesis"]["assignments"] = [1]

    with pytest.raises(
        OptimizationLaunchInputError,
        match="assignment 0",
    ):
        OptimizationLaunchInputParser().parse(source)
