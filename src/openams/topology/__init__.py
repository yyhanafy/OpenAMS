"""SPICE topology extraction and connectivity queries."""

from .errors import (
    DuplicateDeviceError,
    MalformedElementError,
    TopologyError,
    UnsupportedElementError,
    UnsupportedHierarchyError,
)
from .hierarchy import (
    HierarchyExpansion,
    SubcircuitDefinition,
    expand_spice_hierarchy_sources,
    included_source_tokens,
    logical_spice_lines,
    parse_spice_hierarchy_sources,
)
from .queries import connected_devices, connected_terminals, device, node
from .spice_parser import parse_spice_circuit
from .subcircuit import (
    ParsedSubcircuit,
    extract_spice_subcircuit,
    parse_spice_subcircuit,
)

__all__ = [
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
]
