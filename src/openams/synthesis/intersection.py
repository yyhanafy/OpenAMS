"""Deterministic intersection of explicit named regions."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import prod
from typing import Sequence

from .constraints import CircuitConstraint
from .errors import CombinationBudgetExceededError, InvalidRegionError
from .model import CircuitRegion, CircuitRow, RegionInput, RejectedCombination


@dataclass(frozen=True)
class IntersectionPolicy:
    max_combinations: int = 1_000_000
    collect_all_failures: bool = True
    retain_rejected: bool = True
    max_retained_rejections: int = 10_000

    def __post_init__(self) -> None:
        if self.max_combinations <= 0:
            raise InvalidRegionError("max_combinations must be positive")
        if self.max_retained_rejections < 0:
            raise InvalidRegionError("max_retained_rejections must be non-negative")


class RegionIntersection:
    """Join complete rows without breaking within-device correlations."""

    def __init__(
        self,
        constraints: Sequence[CircuitConstraint] = (),
        policy: IntersectionPolicy | None = None,
    ) -> None:
        names = tuple(constraint.name for constraint in constraints)
        if len(set(names)) != len(names):
            raise InvalidRegionError("intersection constraint names must be unique")
        self._constraints = tuple(constraints)
        self._policy = policy or IntersectionPolicy()

    def build(self, inputs: Sequence[RegionInput]) -> CircuitRegion:
        regions = tuple(inputs)
        if not regions:
            raise InvalidRegionError("intersection requires at least one input region")
        names = tuple(region.name for region in regions)
        if len(set(names)) != len(names):
            raise InvalidRegionError("input region names must be unique")

        possible = prod(len(region.rows) for region in regions)
        if possible > self._policy.max_combinations:
            raise CombinationBudgetExceededError(
                f"intersection would evaluate {possible} combinations; "
                f"budget is {self._policy.max_combinations}"
            )

        retained: list[CircuitRow] = []
        rejected: list[RejectedCombination] = []
        failure_counts = {constraint.name: 0 for constraint in self._constraints}
        rejected_count = 0

        enumerated = [tuple(enumerate(region.rows)) for region in regions]
        for combination in product(*enumerated):
            values = {}
            indices = {}
            for region, (index, source_row) in zip(regions, combination, strict=True):
                indices[region.name] = index
                for field, value in source_row.items():
                    values[f"{region.name}.{field}"] = value

            failures: list[str] = []
            reasons: list[str] = []
            for constraint in self._constraints:
                decision = constraint.evaluate(values)
                if decision.accepted:
                    continue
                failures.append(constraint.name)
                reasons.append(decision.reason)
                failure_counts[constraint.name] += 1
                if not self._policy.collect_all_failures:
                    break

            if failures:
                rejected_count += 1
                if (
                    self._policy.retain_rejected
                    and len(rejected) < self._policy.max_retained_rejections
                ):
                    rejected.append(RejectedCombination(indices, tuple(failures), tuple(reasons)))
                continue
            retained.append(CircuitRow(values, indices))

        return CircuitRegion(
            inputs=regions,
            rows=tuple(retained),
            rejected=tuple(rejected),
            constraint_names=tuple(constraint.name for constraint in self._constraints),
            metadata={
                "candidate_combination_count": possible,
                "retained_combination_count": len(retained),
                "rejected_combination_count": rejected_count,
                "retained_rejection_record_count": len(rejected),
                "constraint_failure_counts": failure_counts,
                "source_correlations_preserved": True,
                "intersection_method": "explicit_cartesian_filter",
                "interpolation_used": False,
            },
        )
