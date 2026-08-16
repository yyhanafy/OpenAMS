"""Composition adapters between OpenAMS boundary and domain packages."""

from .technology_csv import (
    build_characterization_table,
    load_characterization_table_csv,
)

__all__ = [
    "build_characterization_table",
    "load_characterization_table_csv",
]
