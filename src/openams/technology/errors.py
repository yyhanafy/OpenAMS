"""Technology-layer exceptions."""


class TechnologyError(RuntimeError):
    """Base class for technology failures."""


class TechnologyValidationError(TechnologyError, ValueError):
    """Raised when a technology declaration is structurally invalid."""


class TechnologyCapabilityError(TechnologyError):
    """Raised when a backend cannot satisfy a declared request."""


class TechnologyLookupError(TechnologyError):
    """Raised when a backend lookup cannot be completed."""
