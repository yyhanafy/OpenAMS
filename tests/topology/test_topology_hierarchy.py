import pytest

from openams.topology import (
    UnsupportedHierarchyError,
    expand_spice_hierarchy_sources,
    parse_spice_hierarchy_sources,
)


def test_recursively_expands_preloaded_sources() -> None:
    sources = {
        "leaf.spice": """\
.subckt leaf d g s b
XM1 d g s b sky130_fd_pr__nfet_01v8 w=2u l=1u
.ends leaf
""",
        "middle.spice": """\
.subckt middle out gate source bulk
XLEAF out gate source bulk leaf
C1 out source 1p
.ends middle
""",
        "top.spice": """\
.subckt top out gate source bulk
XMID out gate source bulk middle
.ends top
""",
    }

    expansion = expand_spice_hierarchy_sources(
        sources,
        top_subcircuit="top",
    )
    assert expansion.expanded_instance_count == 2
    assert expansion.primitive_device_count == 2

    circuit = parse_spice_hierarchy_sources(
        sources,
        top_subcircuit="top",
    )
    assert set(circuit.devices) == {"XXMID.XLEAF.M1", "CXMID.1"}


def test_detects_recursive_cycle_in_preloaded_sources() -> None:
    sources = {
        "cycle.spice": """\
.subckt A x y
XB x y B
.ends A
.subckt B x y
XA x y A
.ends B
"""
    }
    with pytest.raises(UnsupportedHierarchyError, match="recursive"):
        expand_spice_hierarchy_sources(sources, top_subcircuit="A")
