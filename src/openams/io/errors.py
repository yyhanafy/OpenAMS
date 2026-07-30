"""I/O-layer exceptions."""


class InputError(ValueError):
    """Raised when an external OpenAMS input cannot be read or interpreted."""


class SerializationDependencyError(InputError):
    """Raised when an optional serialization library is unavailable."""
