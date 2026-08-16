"""Immutable public model for explicit feasible technology regions."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from openams.technology.adaptive import AdaptiveTable, GeneratedPoint, SamplingDomain


@dataclass(frozen=True)
class ConstraintDecision:
    """Result of evaluating one constraint against one correlated row."""

    accepted: bool
    reason: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True)
class RejectedPoint:
    """A rejected correlated point and the constraints that rejected it."""

    point: GeneratedPoint
    failed_constraints: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FeasibleRegion:
    """Explicit retained rows plus complete construction provenance."""

    source_table: AdaptiveTable
    points: tuple[GeneratedPoint, ...]
    rejected: tuple[RejectedPoint, ...]
    constraint_names: tuple[str, ...]
    next_sampling_domain: SamplingDomain | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def is_empty(self) -> bool:
        return not self.points

    @property
    def retained_count(self) -> int:
        return len(self.points)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def table(self) -> AdaptiveTable:
        """Return the retained region as another explicit adaptive table."""
        return AdaptiveTable(
            points=self.points,
            domain=self.source_table.domain,
            model_identity=self.source_table.model_identity,
            generation_level=self.source_table.generation_level,
            metadata={
                **self.source_table.metadata,
                **self.metadata,
                "feasible_region": True,
                "retained_point_count": self.retained_count,
            },
        )

    def rows(self) -> tuple[dict[str, Any], ...]:
        return self.table().rows()
