def test_topology_public_api() -> None:
    import openams.topology as topology

    assert set(topology.__all__) == {
        "DuplicateDeviceError",
        "MalformedElementError",
        "ParsedSubcircuit",
        "TopologyError",
        "UnsupportedElementError",
        "UnsupportedHierarchyError",
        "connected_devices",
        "connected_terminals",
        "device",
        "extract_spice_subcircuit",
        "node",
        "parse_spice_circuit",
        "parse_spice_subcircuit",
    }
