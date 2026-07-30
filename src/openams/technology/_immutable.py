"""Immutable-value helpers local to the technology contract."""

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


def optional_name(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return require_name(value, field_name)


def require_finite(value: int | float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def require_positive(value: int | float, field_name: str) -> float:
    result = require_finite(value, field_name)
    if result <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return result


def freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    return MappingProxyType(dict(value))


def freeze_numeric_mapping(
    value: Mapping[object, int | float] | None,
    *,
    field_name: str,
    key_type: type,
) -> Mapping[object, float]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")

    result: dict[object, float] = {}
    for key, raw in value.items():
        if not isinstance(key, key_type):
            raise TypeError(
                f"{field_name} keys must be {key_type.__name__} values"
            )
        result[key] = require_finite(raw, f"{field_name}[{key!r}]")
    return MappingProxyType(result)
