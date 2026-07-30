from dataclasses import FrozenInstanceError

import pytest

from openams.model import (
    Analysis,
    AnalysisKind,
    Assignment,
    AssignmentStatus,
    Circuit,
    ComparisonRelation,
    Constraint,
    ConstraintKind,
    Device,
    DeviceKind,
    DeviceQuery,
    DeviceSolution,
    EvaluationResult,
    Node,
    Quantity,
    SimulationResult,
    Specification,
    SpecificationSeverity,
    TechnologyModel,
    Variable,
    VariableRole,
)


def make_circuit() -> Circuit:
    nodes = {
        "vdd": Node("vdd"),
        "vout": Node("vout"),
        "vss": Node("vss"),
    }
    device = Device(
        name="M1",
        kind=DeviceKind.MOS,
        model="nfet",
        terminals={"drain": "vout", "gate": "vdd", "source": "vss", "bulk": "vss"},
        parameters={"width": "device.M1.width"},
    )
    variable = Variable(
        name="device.M1.width",
        quantity=Quantity.LENGTH,
        unit="m",
        role=VariableRole.TECHNOLOGY_SOLVED,
    )
    constraint = Constraint(
        name="positive_width",
        kind=ConstraintKind.INEQUALITY,
        expression="device.M1.width > 0",
        source="design_rules",
        variables=("device.M1.width",),
    )
    analysis = Analysis("dc", AnalysisKind.DC_OPERATING_POINT)
    specification = Specification(
        name="output_min",
        variable="node.vout.voltage",
        relation=ComparisonRelation.GE,
        target=0.5,
        unit="V",
        severity=SpecificationSeverity.REQUIRED,
    )
    return Circuit(
        name="one_transistor",
        nodes=nodes,
        devices={"M1": device},
        variables={"device.M1.width": variable},
        constraints=(constraint,),
        analyses=(analysis,),
        specifications=(specification,),
    )


def test_circuit_constructs_and_is_immutable() -> None:
    circuit = make_circuit()

    assert circuit.devices["M1"].terminals["drain"] == "vout"
    with pytest.raises(TypeError):
        circuit.nodes["new"] = Node("new")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        circuit.name = "changed"  # type: ignore[misc]


def test_circuit_rejects_unknown_terminal_node() -> None:
    with pytest.raises(ValueError, match="unknown nodes"):
        Circuit(
            name="bad",
            nodes={"vss": Node("vss")},
            devices={
                "M1": Device(
                    name="M1",
                    kind=DeviceKind.MOS,
                    model="nfet",
                    terminals={"drain": "missing", "source": "vss"},
                )
            },
        )


def test_circuit_rejects_unknown_constraint_variable() -> None:
    with pytest.raises(ValueError, match="unknown variables"):
        Circuit(
            name="bad",
            nodes={"vss": Node("vss")},
            devices={},
            constraints=(
                Constraint(
                    name="bad_reference",
                    kind=ConstraintKind.EQUALITY,
                    expression="missing == 1",
                    source="test",
                    variables=("missing",),
                ),
            ),
        )


def test_assignment_copies_input_mapping() -> None:
    source = {"device.M1.width": 2e-6}
    assignment = Assignment(
        name="assignment_000001",
        values=source,
        status=AssignmentStatus.RESOLVED,
    )
    source["device.M1.width"] = 9e-6

    assert assignment.values["device.M1.width"] == 2e-6
    with pytest.raises(TypeError):
        assignment.values["device.M1.width"] = 4e-6  # type: ignore[index]


def test_device_query_requires_disjoint_known_and_unknown() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        DeviceQuery(
            device_kind="mos",
            known={"width": 1e-6},
            solve_for=("width",),
        )


def test_technology_protocol_is_runtime_checkable() -> None:
    class FakeTechnology:
        def solve(self, query: DeviceQuery) -> DeviceSolution:
            return DeviceSolution(values={query.solve_for[0]: 2e-6}, valid=True)

    technology = FakeTechnology()
    assert isinstance(technology, TechnologyModel)
    solution = technology.solve(
        DeviceQuery(device_kind="mos", known={"id": 10e-6}, solve_for=("width",))
    )
    assert solution.valid
    assert solution.values["width"] == 2e-6


def test_simulation_and_evaluation_results_are_normalized_and_immutable() -> None:
    simulation = SimulationResult(
        assignment_name="assignment_000001",
        simulator="ngspice",
        analyses={"dc": {"node.vout.voltage": 1.2}},
        success=True,
        artifacts={"netlist": "runtime/rendered.spice"},
    )
    evaluation = EvaluationResult(
        assignment_name="assignment_000001",
        passed=True,
        checks={"output_min": True},
        score=0.95,
        margins={"output_min": 0.7},
    )

    assert simulation.analyses["dc"]["node.vout.voltage"] == 1.2
    assert evaluation.checks["output_min"] is True
    with pytest.raises(TypeError):
        simulation.analyses["dc"]["node.vout.voltage"] = 0.0  # type: ignore[index]


def test_duplicate_constraint_names_are_rejected() -> None:
    constraint = Constraint(
        name="same",
        kind=ConstraintKind.LOGICAL,
        expression="true",
        source="test",
    )
    with pytest.raises(ValueError, match="constraint names must be unique"):
        Circuit(
            name="duplicate",
            nodes={"0": Node("0")},
            devices={},
            constraints=(constraint, constraint),
        )


def test_public_enums_are_string_compatible() -> None:
    assert VariableRole.INDEPENDENT == "independent"
    assert AnalysisKind.AC == "ac"
    assert ComparisonRelation.GE == ">="
