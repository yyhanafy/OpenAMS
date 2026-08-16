"""Internal helpers for immutable OpenAMS domain objects."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


def immutable_mapping(value: Mapping[K, V] | None = None) -> Mapping[K, V]:
    """Return an immutable shallow copy of *value*.

    Domain objects are intentionally shallowly immutable. Values placed inside a
    mapping must therefore also be immutable domain values or scalar data.
    """

    return MappingProxyType(dict(value or {}))


def require_nonempty(value: str, field_name: str) -> str:
    """Validate and return a non-empty, stripped string."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def require_finite_number(value: int | float, field_name: str) -> float:
    """Validate and return a finite float."""

    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized
