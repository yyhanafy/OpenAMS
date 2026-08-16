"""Topology-layer exceptions."""


class TopologyError(ValueError):
    """Base class for circuit-topology failures."""


class MalformedElementError(TopologyError):
    """Raised when a supported SPICE element has invalid syntax."""


class UnsupportedElementError(TopologyError):
    """Raised when an element is outside the initial topology subset."""


class UnsupportedHierarchyError(TopologyError):
    """Raised when hierarchy would need semantic expansion."""


class DuplicateDeviceError(TopologyError):
    """Raised when a flat circuit repeats a device identifier."""
