def test_topology_public_api() -> None:
    import openams.topology as topology

    assert set(topology.__all__) == {
        "DuplicateDeviceError",
        "MalformedElementError",
        "TopologyError",
        "UnsupportedElementError",
        "UnsupportedHierarchyError",
        "connected_devices",
        "connected_terminals",
        "device",
        "node",
        "parse_spice_circuit",
    }
