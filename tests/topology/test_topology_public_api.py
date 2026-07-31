def test_topology_public_api() -> None:
    import openams.topology as topology

    assert set(topology.__all__) == {
        "DuplicateDeviceError",
        "HierarchyExpansion",
        "MalformedElementError",
        "ParsedSubcircuit",
        "SubcircuitDefinition",
        "TopologyError",
        "UnsupportedElementError",
        "UnsupportedHierarchyError",
        "connected_devices",
        "connected_terminals",
        "device",
        "expand_spice_hierarchy_sources",
        "extract_spice_subcircuit",
        "included_source_tokens",
        "logical_spice_lines",
        "node",
        "parse_spice_circuit",
        "parse_spice_hierarchy_sources",
        "parse_spice_subcircuit",
    }
