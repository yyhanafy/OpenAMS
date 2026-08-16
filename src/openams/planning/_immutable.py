"""Immutable-value helpers for execution planning."""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Mapping


def require_name(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def freeze_names(values: object, field_name: str) -> frozenset[str]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an iterable of names")
    try:
        normalized = frozenset(
            require_name(value, f"{field_name} item") for value in values  # type: ignore[arg-type]
        )
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable of names") from None
    return normalized


def freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("mapping value must be a mapping")
    return MappingProxyType(dict(value))


def freeze_numeric_mapping(
    value: Mapping[str, int | float] | None,
    field_name: str,
) -> Mapping[str, float]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")

    result: dict[str, float] = {}
    for key, raw in value.items():
        name = require_name(key, f"{field_name} key")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"{field_name}[{name!r}] must be a real number")
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError(f"{field_name}[{name!r}] must be finite")
        result[name] = number
    return MappingProxyType(result)
