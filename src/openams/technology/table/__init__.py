"""Immutable generic characterization-table backend."""

from .backend import TableTechnologyBackend
from .errors import (
    DuplicateCharacterizationPointError,
    TableLookupError,
    TableValidationError,
)
from .model import (
    BracketAxis,
    BracketResult,
    CharacterizationTable,
)
from .queries import (
    bracket_points,
    exact_point,
    nearest_points,
    points_for_model,
)
from .validation import validate_characterization_table

__all__ = [
    "BracketAxis",
    "BracketResult",
    "CharacterizationTable",
    "DuplicateCharacterizationPointError",
    "TableLookupError",
    "TableTechnologyBackend",
    "TableValidationError",
    "bracket_points",
    "exact_point",
    "nearest_points",
    "points_for_model",
    "validate_characterization_table",
]
