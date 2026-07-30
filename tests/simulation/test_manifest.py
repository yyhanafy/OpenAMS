from dataclasses import dataclass

import pytest

from openams.model import Assignment, AssignmentStatus
from openams.simulation import (
    DirectSimulationInput,
    DirectSimulationManifestBuilder,
    InvalidExecutionPlanError,
    InvalidSimulationManifestError,
    SimulationBackend,
    SimulationRunRequest,
    SimulationTemplate,
)


@dataclass(frozen=True)
class FakePlan:
    name: str = "assignment_000000"
    route: str = "direct_simulation"
    stages: tuple[str, ...] = ("validate_inputs", "simulate", "verify_specifications")
    requires_executable_contract: bool = False
    provenance: dict | None = None


def assignment(name="assignment_000000", status=AssignmentStatus.SIMULATION_READY):
    return Assignment(
        name=name,
        values={"device.M1.width": 2.0, "device.M5.current": 20e-6},
        status=status,
        provenance={"source_row_index": 4},
    )


def template():
    return SimulationTemplate(
        name="two_stage",
        source="examples/two_stage_opamp/inputs/two_stage.spice",
        parameter_bindings={
            "device.M1.width": "W_M1",
            "device.M5.current": "I_M5",
        },
    )


def test_builds_backend_neutral_manifest() -> None:
    manifest = DirectSimulationManifestBuilder().build(
        name="two_stage_fixed",
        backend=SimulationBackend(name="ngspice"),
        template=template(),
        inputs=(DirectSimulationInput(assignment(), FakePlan()),),
        analyses=("dc", "ac"),
    )

    assert manifest.case_count == 1
    assert manifest.backend.name == "ngspice"
    assert manifest.cases[0].rendered_parameters == {"W_M1": 2.0, "I_M5": 20e-6}
    assert manifest.cases[0].analyses == ("dc", "ac")


def test_preserves_assignment_and_plan_provenance() -> None:
    manifest = DirectSimulationManifestBuilder().build(
        name="m",
        backend=SimulationBackend(name="generic"),
        template=template(),
        inputs=(DirectSimulationInput(assignment(), FakePlan(provenance={"route": "fixed"}), {"batch": 2}),),
        analyses=("dc",),
    )
    provenance = manifest.cases[0].provenance
    assert provenance["assignment_provenance"]["source_row_index"] == 4
    assert provenance["plan_provenance"]["route"] == "fixed"
    assert provenance["batch"] == 2


def test_multiple_assignments_produce_deterministic_cases() -> None:
    inputs = tuple(
        DirectSimulationInput(assignment(f"assignment_{i:06d}"), FakePlan(name=f"assignment_{i:06d}"))
        for i in range(3)
    )
    manifest = DirectSimulationManifestBuilder().build(
        name="m", backend=SimulationBackend(name="generic"), template=template(),
        inputs=inputs, analyses=("dc",)
    )
    assert [case.name for case in manifest.cases] == [
        "assignment_000000", "assignment_000001", "assignment_000002"
    ]


def test_non_direct_route_is_rejected() -> None:
    with pytest.raises(InvalidExecutionPlanError, match="not 'direct_simulation'"):
        DirectSimulationManifestBuilder().build(
            name="m", backend=SimulationBackend(name="generic"), template=template(),
            inputs=(DirectSimulationInput(assignment(), FakePlan(route="optimization")),),
            analyses=("dc",)
        )


def test_plan_without_simulate_stage_is_rejected() -> None:
    with pytest.raises(InvalidExecutionPlanError, match="no simulate stage"):
        DirectSimulationManifestBuilder().build(
            name="m", backend=SimulationBackend(name="generic"), template=template(),
            inputs=(DirectSimulationInput(assignment(), FakePlan(stages=("validate_inputs",))),),
            analyses=("dc",)
        )


def test_missing_template_variable_is_rejected() -> None:
    bad = SimulationTemplate(
        name="bad", source="x.spice",
        parameter_bindings={"device.M6.width": "W_M6"},
    )
    with pytest.raises(InvalidSimulationManifestError, match="missing template variable"):
        DirectSimulationManifestBuilder().build(
            name="m", backend=SimulationBackend(name="generic"), template=bad,
            inputs=(DirectSimulationInput(assignment(), FakePlan()),), analyses=("dc",)
        )


def test_simulation_run_request_is_backend_agnostic() -> None:
    manifest = DirectSimulationManifestBuilder().build(
        name="m", backend=SimulationBackend(name="generic"), template=template(),
        inputs=(DirectSimulationInput(assignment(), FakePlan()),), analyses=("dc",)
    )
    request = SimulationRunRequest(
        manifest=manifest, workspace="runtime/two_stage", max_workers=4,
        keep_intermediate_files=True,
    )
    assert request.max_workers == 4
    assert request.keep_intermediate_files is True


def test_template_rejects_duplicate_parameter_targets() -> None:
    with pytest.raises(InvalidSimulationManifestError, match="bound more than once"):
        SimulationTemplate(
            name="bad", source="x.spice",
            parameter_bindings={"a": "P", "b": "P"},
        )
