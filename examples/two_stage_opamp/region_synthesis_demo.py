"""Minimal executable demonstration of hierarchical region synthesis."""
from openams.synthesis import (
    CanonicalConstraintRecord,
    HierarchicalSynthesisWorkflow,
    RegionBinding,
    RegionInput,
    SynthesisStage,
)


def bind(name, rows, mapping):
    return RegionBinding(name, RegionInput(name, tuple(rows)), mapping)


bindings = (
    bind("M1", ({"id": 10e-6, "w": 2.0},), {"device.M1.current": "id", "device.M1.width": "w"}),
    bind("M2", ({"id": 10e-6, "w": 2.0},), {"device.M2.current": "id", "device.M2.width": "w"}),
    bind("M5", ({"id": 20e-6, "w": 8.0},), {"device.M5.current": "id", "device.M5.width": "w"}),
)

stages = (
    SynthesisStage(
        "input_pair",
        ("M1", "M2"),
        (
            CanonicalConstraintRecord("equal_current", "device.M1.current == device.M2.current"),
            CanonicalConstraintRecord("equal_width", "device.M1.width == device.M2.width"),
        ),
    ),
    SynthesisStage(
        "input_bias_network",
        ("input_pair", "M5"),
        (
            CanonicalConstraintRecord(
                "tail_kcl",
                "device.M5.current == device.M1.current + device.M2.current",
                kind="topology_derived",
                source="topology",
            ),
        ),
    ),
)

if __name__ == "__main__":
    result = HierarchicalSynthesisWorkflow().run(bindings, stages)
    print("retained assignments:", result.final.retained_count)
    for row in result.final.region.dictionaries():
        print(row)
