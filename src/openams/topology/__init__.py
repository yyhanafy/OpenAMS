"""SPICE topology extraction and connectivity queries."""

from .errors import (
    DuplicateDeviceError,
    MalformedElementError,
    TopologyError,
    UnsupportedElementError,
    UnsupportedHierarchyError,
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
]
