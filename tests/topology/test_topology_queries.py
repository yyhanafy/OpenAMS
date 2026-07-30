import pytest

from openams.topology import (
    TopologyError,
    connected_devices,
    connected_terminals,
    device,
    node,
    parse_spice_circuit,
)


def test_connectivity_queries() -> None:
    circuit = parse_spice_circuit(
        """
        M1 n1 vin tail 0 nmos W=2u L=0.5u
        R1 n1 vdd 10k
        C1 n1 0 1p
        """
    )

    assert node(circuit, "n1").name == "n1"
    assert device(circuit, "M1").name == "M1"
    assert [item.name for item in connected_devices(circuit, "n1")] == [
        "M1",
        "R1",
        "C1",
    ]
    assert [(name, terminal.name) for name, terminal in connected_terminals(circuit, "n1")] == [
        ("M1", "drain"),
        ("R1", "positive"),
        ("C1", "positive"),
    ]


def test_unknown_query_identity_is_explicit() -> None:
    circuit = parse_spice_circuit("R1 a b 1k")
    with pytest.raises(TopologyError, match="unknown node"):
        node(circuit, "missing")
    with pytest.raises(TopologyError, match="unknown device"):
        device(circuit, "missing")
