from math import inf

import pytest

from openams.model import AssignmentStatus
from openams.planning import ExecutionRoute, ExecutionStage
from openams.synthesis import (
    CircuitRegion,
    CircuitRegionAssignmentEmitter,
    CircuitRow,
    FixedAssignmentPolicy,
    InvalidRegionError,
    MissingFieldError,
    RegionInput,
)


def make_region(*rows: CircuitRow) -> CircuitRegion:
    return CircuitRegion(
        inputs=(RegionInput("final", tuple(row.values for row in rows)),),
        rows=rows,
        rejected=(),
        constraint_names=("tail_kcl",),
        metadata={"intersection_method": "planned_indexed", "stage": "full_circuit"},
    )


def test_emits_simulation_ready_assignments_and_direct_plans() -> None:
    region = make_region(
        CircuitRow(
            values={"input.M1.w": 2.0, "tail.M5.id": 20e-6},
            source_indices={"input_pair": 3, "M5": 1},
        )
    )
    batch = CircuitRegionAssignmentEmitter().emit(
        region,
        {
            "device.M1.width": "input.M1.w",
            "device.M5.current": "tail.M5.id",
        },
    )

    assert batch.count == 1
    record = batch.records[0]
    assert record.assignment.name == "assignment_000000"
    assert record.assignment.status is AssignmentStatus.SIMULATION_READY
    assert record.assignment.values["device.M1.width"] == 2.0
    assert record.plan.route is ExecutionRoute.DIRECT_SIMULATION
    assert ExecutionStage.BUILD_EXECUTABLE_CONTRACT not in record.plan.stages
    assert record.source_indices == {"input_pair": 3, "M5": 1}


def test_names_are_deterministic_and_configurable() -> None:
    region = make_region(
        CircuitRow(values={"x": 1.0}, source_indices={"a": 0}),
        CircuitRow(values={"x": 2.0}, source_indices={"a": 1}),
    )
    emitter = CircuitRegionAssignmentEmitter(
        FixedAssignmentPolicy(name_prefix="fixed", start_index=7, index_width=4)
    )
    batch = emitter.emit(region, {"device.M1.width": "x"})

    assert [item.name for item in batch.assignments] == ["fixed_0007", "fixed_0008"]


def test_provenance_preserves_region_and_source_rows() -> None:
    row = CircuitRow(values={"x": 1.0}, source_indices={"M1": 4})
    record = CircuitRegionAssignmentEmitter().emit(
        make_region(row), {"device.M1.width": "x"}
    ).records[0]

    assert record.assignment.provenance["source_row_index"] == 0
    assert record.assignment.provenance["source_indices"] == {"M1": 4}
    assert record.assignment.provenance["region_metadata"]["stage"] == "full_circuit"


def test_empty_region_produces_empty_batch() -> None:
    batch = CircuitRegionAssignmentEmitter().emit(
        make_region(), {"device.M1.width": "x"}
    )
    assert batch.count == 0
    assert batch.assignments == ()
    assert batch.plans == ()


def test_missing_mapped_field_is_rejected() -> None:
    region = make_region(CircuitRow(values={"x": 1.0}, source_indices={"M1": 0}))
    with pytest.raises(MissingFieldError, match="missing mapped field"):
        CircuitRegionAssignmentEmitter().emit(
            region, {"device.M1.width": "missing"}
        )


def test_required_variables_must_be_mapped() -> None:
    region = make_region(CircuitRow(values={"x": 1.0}, source_indices={"M1": 0}))
    with pytest.raises(MissingFieldError, match="not mapped"):
        CircuitRegionAssignmentEmitter().emit(
            region,
            {"device.M1.width": "x"},
            required_variables=("device.M1.width", "device.M1.length"),
        )


def test_non_numeric_and_nonfinite_values_are_rejected() -> None:
    text_region = make_region(
        CircuitRow(values={"x": "wide"}, source_indices={"M1": 0})
    )
    with pytest.raises(InvalidRegionError, match="must be numeric"):
        CircuitRegionAssignmentEmitter().emit(
            text_region, {"device.M1.width": "x"}
        )

    inf_region = make_region(CircuitRow(values={"x": inf}, source_indices={"M1": 0}))
    with pytest.raises(InvalidRegionError, match="must be finite"):
        CircuitRegionAssignmentEmitter().emit(
            inf_region, {"device.M1.width": "x"}
        )


def test_strict_mapping_can_reject_unmapped_fields() -> None:
    region = make_region(
        CircuitRow(values={"x": 1.0, "debug": 9.0}, source_indices={"M1": 0})
    )
    emitter = CircuitRegionAssignmentEmitter(
        FixedAssignmentPolicy(reject_unmapped_row_fields=True)
    )
    with pytest.raises(InvalidRegionError, match="unmapped fields"):
        emitter.emit(region, {"device.M1.width": "x"})
