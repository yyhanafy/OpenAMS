import math

import pytest

from openams.topology import (
    DuplicateDeviceError,
    UnsupportedElementError,
    UnsupportedHierarchyError,
    parse_spice_circuit,
)


def test_parse_flat_mos_and_passives() -> None:
    circuit = parse_spice_circuit(
        """
        * two-device fragment
        M1 n1 vip tail 0 nmos W=2u L=0.5u
        XMP n1 vin vdd vdd sky130_fd_pr__pfet_01v8
        + W=4u L=0.5u
        R1 n1 vout 10k
        C1 vout 0 3p
        VDD vdd 0 DC 1.8
        IBIAS tail 0 30u
        .op
        .end
        """,
        name="fragment",
    )

    assert circuit.name == "fragment"
    assert set(circuit.devices) == {"M1", "XMP", "R1", "C1", "VDD", "IBIAS"}
    assert set(circuit.nodes) == {"0", "n1", "vip", "vin", "tail", "vdd", "vout"}

    m1 = circuit.devices["M1"]
    assert m1.kind == "mos" or getattr(m1.kind, "value", None) == "mos"
    assert m1.model == "nmos"
    assert m1.terminals["drain"] == "n1"
    assert math.isclose(m1.parameters["w"], 2e-6)
    assert math.isclose(m1.parameters["l"], 0.5e-6)

    assert circuit.devices["R1"].parameters["value"] == "10k"
    assert circuit.devices["VDD"].parameters["value"] == "DC 1.8"


def test_inline_comment_is_removed() -> None:
    circuit = parse_spice_circuit("R1 a b 1k $ load resistor")
    assert circuit.devices["R1"].parameters["value"] == "1k"


def test_duplicate_names_are_case_insensitive() -> None:
    with pytest.raises(DuplicateDeviceError, match="duplicate device"):
        parse_spice_circuit("Rload a b 1k\nrLOAD b 0 2k")


def test_hierarchy_is_rejected() -> None:
    with pytest.raises(UnsupportedHierarchyError, match="hierarchy"):
        parse_spice_circuit(".subckt block a b\nR1 a b 1k\n.ends")


def test_arbitrary_x_instance_is_rejected() -> None:
    with pytest.raises(UnsupportedHierarchyError, match="not recognizably MOS"):
        parse_spice_circuit("X1 a b arbitrary_block")


def test_unsupported_element_is_rejected() -> None:
    with pytest.raises(UnsupportedElementError, match="prefix"):
        parse_spice_circuit("D1 a b diode_model")
