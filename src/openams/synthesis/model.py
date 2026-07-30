"""Immutable models for explicit region intersection."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from openams.technology.feasible import FeasibleRegion

from .errors import InvalidRegionError


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class RegionInput:
    """Named explicit rows participating in one circuit intersection."""

    name: str
    rows: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidRegionError("region name must be non-empty")
        frozen_rows = tuple(_freeze(row) for row in self.rows)
        object.__setattr__(self, "rows", frozen_rows)
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @classmethod
    def from_feasible_region(cls, name: str, region: FeasibleRegion) -> "RegionInput":
        return cls(
            name=name,
            rows=region.rows(),
            metadata={
                "source_kind": "technology_feasible_region",
                "source_model": region.source_table.model_identity,
                "source_retained_count": region.retained_count,
            },
        )


@dataclass(frozen=True)
class ConstraintDecision:
    accepted: bool
    reason: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _freeze(self.diagnostics))


@dataclass(frozen=True)
class RejectedCombination:
    """One rejected tuple of source-row indices."""

    source_indices: Mapping[str, int]
    failed_constraints: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_indices", _freeze(self.source_indices))


@dataclass(frozen=True)
class CircuitRow:
    """One retained circuit operating assignment with full provenance."""

    values: Mapping[str, Any]
    source_indices: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _freeze(self.values))
        object.__setattr__(self, "source_indices", _freeze(self.source_indices))


@dataclass(frozen=True)
class CircuitRegion:
    """Explicit circuit-feasible rows produced by region intersection."""

    inputs: tuple[RegionInput, ...]
    rows: tuple[CircuitRow, ...]
    rejected: tuple[RejectedCombination, ...]
    constraint_names: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def retained_count(self) -> int:
        return len(self.rows)

    @property
    def rejected_count(self) -> int:
        return int(self.metadata.get("rejected_combination_count", len(self.rejected)))

    def dictionaries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row.values) for row in self.rows)
