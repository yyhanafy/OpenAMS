from pathlib import Path

import pytest

from openams.topology import (
    MalformedElementError,
    UnsupportedHierarchyError,
    extract_spice_subcircuit,
    parse_spice_subcircuit,
)


TWO_STAGE = """\
* example
.subckt two_stage_opamp inp inn out vdd vss vbias
XM1 n1 inp ntail vss sky130_fd_pr__nfet_01v8 L=0.5 W=2
XM2 n2 inn ntail vss sky130_fd_pr__nfet_01v8 L=0.5 W=2
XM3 n1 n1 vdd vdd sky130_fd_pr__pfet_01v8 L=0.5 W=5
XM4 n2 n1 vdd vdd sky130_fd_pr__pfet_01v8 L=0.5 W=5
XM5 ntail vbias vss vss sky130_fd_pr__nfet_01v8 L=0.5 W=4
XM6 out n2 vdd vdd sky130_fd_pr__pfet_01v8 L=0.5 W=8
XM7 out vbias vss vss sky130_fd_pr__nfet_01v8 L=0.5 W=4
Cc n2 out 3p
.ends two_stage_opamp
"""


def test_extracts_named_subcircuit_and_ports() -> None:
    selected = extract_spice_subcircuit(
        TWO_STAGE,
        subcircuit="two_stage_opamp",
    )

    assert selected.name == "two_stage_opamp"
    assert selected.ports == ("inp", "inn", "out", "vdd", "vss", "vbias")
    assert ".subckt" not in selected.body.lower()
    assert ".ends" not in selected.body.lower()
    assert "XM1" in selected.body
    assert "Cc" in selected.body


def test_parses_single_level_subcircuit_with_existing_flat_parser() -> None:
    circuit = parse_spice_subcircuit(
        TWO_STAGE,
        subcircuit="two_stage_opamp",
    )

    assert circuit.name == "two_stage_opamp"
    assert set(circuit.devices) == {
        "XM1", "XM2", "XM3", "XM4", "XM5", "XM6", "XM7", "Cc"
    }
    assert circuit.devices["XM1"].terminals == {
        "drain": "n1",
        "gate": "inp",
        "source": "ntail",
        "bulk": "vss",
    }
    assert circuit.devices["XM6"].terminals["gate"] == "n2"
    assert circuit.devices["Cc"].terminals == {
        "positive": "n2",
        "negative": "out",
    }


def test_nested_subcircuit_is_rejected() -> None:
    text = """\
.subckt outer a b
.subckt inner x y
R1 x y 1k
.ends inner
.ends outer
"""
    with pytest.raises(UnsupportedHierarchyError, match="nested"):
        extract_spice_subcircuit(text, subcircuit="outer")


def test_missing_subcircuit_is_explicit() -> None:
    with pytest.raises(UnsupportedHierarchyError, match="was not found"):
        extract_spice_subcircuit(TWO_STAGE, subcircuit="missing")


def test_missing_ends_is_explicit() -> None:
    text = ".subckt block a b\nR1 a b 1k\n"
    with pytest.raises(MalformedElementError, match="no matching"):
        extract_spice_subcircuit(text, subcircuit="block")


def test_official_two_stage_input_parses_when_present() -> None:
    path = Path("examples/two_stage_opamp/inputs/netlist.spice")
    if not path.is_file():
        pytest.skip("official two-stage input is not installed")

    circuit = parse_spice_subcircuit(
        path.read_text(encoding="utf-8"),
        subcircuit="two_stage_opamp",
    )

    assert circuit.name == "two_stage_opamp"
    assert set(circuit.devices) == {
        "XM1", "XM2", "XM3", "XM4", "XM5", "XM6", "XM7", "Cc"
    }
