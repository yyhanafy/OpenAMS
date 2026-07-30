import pytest

from openams.synthesis import (
    CanonicalConstraintRecord,
    HierarchicalSynthesisWorkflow,
    InvalidRegionError,
    RegionBinding,
    RegionInput,
    SynthesisError,
    SynthesisStage,
)


def device(name, rows, fields):
    return RegionBinding(name, RegionInput(name, tuple(rows)), fields)


def two_stage_bindings():
    return (
        device("M1", [{"id": 10.0, "w": 2.0}, {"id": 15.0, "w": 3.0}],
               {"device.M1.current": "id", "device.M1.width": "w"}),
        device("M2", [{"id": 10.0, "w": 2.0}, {"id": 20.0, "w": 4.0}],
               {"device.M2.current": "id", "device.M2.width": "w"}),
        device("M3", [{"id": 10.0, "w": 5.0}, {"id": 15.0, "w": 6.0}],
               {"device.M3.current": "id", "device.M3.width": "w"}),
        device("M4", [{"id": 10.0, "w": 5.0}, {"id": 15.0, "w": 7.0}],
               {"device.M4.current": "id", "device.M4.width": "w"}),
        device("M5", [{"id": 20.0, "w": 8.0}, {"id": 30.0, "w": 9.0}],
               {"device.M5.current": "id", "device.M5.width": "w"}),
        device("M6", [{"id": 8.0, "w": 4.0}, {"id": 12.0, "w": 6.0}],
               {"device.M6.current": "id", "device.M6.width": "w"}),
        device("M7", [{"id": 8.0, "w": 2.0}, {"id": 12.0, "w": 3.0}],
               {"device.M7.current": "id", "device.M7.width": "w"}),
    )


def two_stage_program():
    return (
        SynthesisStage(
            "input_pair",
            ("M1", "M2"),
            (
                CanonicalConstraintRecord("input_current_match", "device.M1.current == device.M2.current"),
                CanonicalConstraintRecord("input_width_match", "device.M1.width == device.M2.width"),
            ),
        ),
        SynthesisStage(
            "active_load",
            ("M3", "M4"),
            (
                CanonicalConstraintRecord("load_current_match", "device.M3.current == device.M4.current"),
                CanonicalConstraintRecord("load_width_match", "device.M3.width == device.M4.width"),
            ),
        ),
        SynthesisStage(
            "output_stage",
            ("M6", "M7"),
            (
                CanonicalConstraintRecord("output_current_match", "device.M6.current == device.M7.current"),
                CanonicalConstraintRecord("output_width_ratio", "device.M6.width == 2 * device.M7.width"),
            ),
        ),
        SynthesisStage(
            "full_circuit",
            ("input_pair", "active_load", "M5", "output_stage"),
            (
                CanonicalConstraintRecord(
                    "tail_kcl",
                    "device.M5.current == device.M1.current + device.M2.current",
                    kind="topology_derived",
                    source="topology",
                ),
                CanonicalConstraintRecord(
                    "load_tracks_input",
                    "device.M3.current == device.M1.current",
                    source="design_intent",
                ),
            ),
            metadata={"topology": "two_stage_opamp"},
        ),
    )


def test_two_stage_opamp_runs_hierarchically_to_one_assignment():
    result = HierarchicalSynthesisWorkflow().run(two_stage_bindings(), two_stage_program())
    assert tuple(stage.stage.name for stage in result.stages) == (
        "input_pair", "active_load", "output_stage", "full_circuit"
    )
    assert result.stage("input_pair").retained_count == 1
    assert result.stage("active_load").retained_count == 1
    assert result.stage("output_stage").retained_count == 2
    assert result.final.retained_count == 2
    row = result.final.region.rows[0].values
    assert row["input_pair.M1.id"] == 10.0
    assert row["active_load.M3.id"] == 10.0
    assert row["M5.id"] == 20.0


def test_stage_output_carries_canonical_bindings_forward():
    result = HierarchicalSynthesisWorkflow().run(two_stage_bindings(), two_stage_program()[:1])
    binding = result.bindings["input_pair"]
    assert binding.field_map["device.M1.current"] == "M1.id"
    assert binding.field_map["device.M2.width"] == "M2.w"
    assert binding.region.rows[0]["M1.id"] == 10.0


def test_device_stage_uses_indexed_intersection():
    result = HierarchicalSynthesisWorkflow().run(two_stage_bindings(), two_stage_program()[:1])
    assert result.final.region.metadata["intersection_method"] == "planned_indexed_equality_join"


def test_final_stage_preserves_stage_level_provenance():
    result = HierarchicalSynthesisWorkflow().run(two_stage_bindings(), two_stage_program())
    indices = result.final.region.rows[0].source_indices
    assert set(indices) == {"input_pair", "active_load", "M5", "output_stage"}


def test_missing_stage_dependency_is_explicit():
    stage = SynthesisStage("bad", ("missing",), ())
    with pytest.raises(InvalidRegionError, match="unavailable inputs"):
        HierarchicalSynthesisWorkflow().run(two_stage_bindings(), (stage,))


def test_duplicate_stage_output_name_is_rejected():
    stage = SynthesisStage("M1", ("M1",), ())
    with pytest.raises(InvalidRegionError, match="already exists"):
        HierarchicalSynthesisWorkflow().run(two_stage_bindings(), (stage,))


def test_empty_stage_can_be_rejected_by_policy():
    stage = SynthesisStage(
        "empty",
        ("M1", "M2"),
        (CanonicalConstraintRecord("impossible", "device.M1.current == 99 * device.M2.current"),),
    )
    with pytest.raises(SynthesisError, match="empty circuit region"):
        HierarchicalSynthesisWorkflow(reject_empty_stage=True).run(two_stage_bindings(), (stage,))


def test_final_stage_metadata_identifies_real_topology():
    result = HierarchicalSynthesisWorkflow().run(two_stage_bindings(), two_stage_program())
    binding = result.bindings["full_circuit"]
    assert binding.region.metadata["topology"] == "two_stage_opamp"
    assert binding.region.metadata["stage_inputs"] == (
        "input_pair", "active_load", "M5", "output_stage"
    )
