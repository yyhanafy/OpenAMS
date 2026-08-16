"""Metadata-layer exceptions."""


class MetadataError(ValueError):
    """Base class for semantic metadata failures."""


class MetadataValidationError(MetadataError):
    """Raised when metadata violates the canonical semantic schema."""
