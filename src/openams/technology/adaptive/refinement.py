"""Deterministic refinement of surviving local-table cells."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .model import AdaptiveTable, AxisDomain, SamplingDomain


@dataclass(frozen=True)
class RefinementPolicy:
    """Per-axis density multiplier and optional coordinate padding."""

    density_multiplier: int = 2
    padding_fraction: float = 0.0

    def __post_init__(self) -> None:
        if self.density_multiplier < 2:
            raise ValueError("density_multiplier must be at least 2")
        if self.padding_fraction < 0:
            raise ValueError("padding_fraction must be non-negative")


def surviving_domain(
    table: AdaptiveTable,
    predicate: Callable[[dict[str, object]], bool],
    *,
    policy: RefinementPolicy | None = None,
) -> SamplingDomain | None:
    """Bound and densify rows that survived a caller-owned feasibility test.

    The predicate represents circuit-specific technology/design constraints.
    This module deliberately does not know MOS physics, topology, or intent.
    """
    refinement = policy or RefinementPolicy()
    rows = [row for row in table.rows() if predicate(row)]
    if not rows:
        return None

    axes: list[AxisDomain] = []
    for original in table.domain.axes:
        values = [float(row[original.name]) for row in rows]
        lo, hi = min(values), max(values)
        span = original.maximum - original.minimum
        padding = span * refinement.padding_fraction
        lo = max(original.minimum, lo - padding)
        hi = min(original.maximum, hi + padding)
        if lo == hi:
            axes.append(AxisDomain(original.name, lo, hi, 1, original.spacing))
        else:
            count = max(2, (original.count - 1) * refinement.density_multiplier + 1)
            axes.append(AxisDomain(original.name, lo, hi, count, original.spacing))
    return SamplingDomain(tuple(axes))
