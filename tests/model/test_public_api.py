import openams.model as model


def test_expected_public_api_is_exported() -> None:
    expected = {
        "Circuit",
        "Node",
        "Terminal",
        "Device",
        "Variable",
        "Constraint",
        "Assignment",
        "DeviceQuery",
        "DeviceSolution",
        "TechnologyModel",
        "Analysis",
        "SimulationResult",
        "Specification",
        "EvaluationResult",
    }
    assert expected.issubset(set(model.__all__))
