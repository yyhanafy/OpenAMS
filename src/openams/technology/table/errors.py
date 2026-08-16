"""Generic table-backend exceptions."""

from openams.technology import TechnologyLookupError, TechnologyValidationError


class TableValidationError(TechnologyValidationError):
    """Raised when a characterization table is inconsistent."""


class DuplicateCharacterizationPointError(TableValidationError):
    """Raised when an exact operating point appears more than once."""


class TableLookupError(TechnologyLookupError):
    """Raised when a table lookup cannot be completed."""
