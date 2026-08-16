"""Build explicit feasible regions from adaptive technology tables."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from openams.technology.adaptive import AdaptiveTable, RefinementPolicy, surviving_domain

from .constraints import RowConstraint
from .model import FeasibleRegion, RejectedPoint


@dataclass(frozen=True)
class FeasibleRegionPolicy:
    """Controls evaluation and optional next-domain generation."""

    collect_all_failures: bool = True
    generate_next_domain: bool = False
    refinement: RefinementPolicy = RefinementPolicy()


class FeasibleRegionBuilder:
    """Apply generic constraints without separating correlated row values."""

    def __init__(
        self,
        constraints: Sequence[RowConstraint],
        policy: FeasibleRegionPolicy | None = None,
    ) -> None:
        names = tuple(constraint.name for constraint in constraints)
        if len(set(names)) != len(names):
            raise ValueError("feasible-region constraint names must be unique")
        self._constraints = tuple(constraints)
        self._policy = policy or FeasibleRegionPolicy()

    def build(self, table: AdaptiveTable) -> FeasibleRegion:
        retained = []
        rejected = []

        for point, row in zip(table.points, table.rows(), strict=True):
            failures: list[str] = []
            reasons: list[str] = []
            for constraint in self._constraints:
                decision = constraint.evaluate(row)
                if decision.accepted:
                    continue
                failures.append(constraint.name)
                reasons.append(decision.reason)
                if not self._policy.collect_all_failures:
                    break
            if failures:
                rejected.append(RejectedPoint(point, tuple(failures), tuple(reasons)))
            else:
                retained.append(point)

        next_domain = None
        if self._policy.generate_next_domain and retained:
            retained_keys = {
                tuple(sorted({**point.coordinates, **point.quantities}.items()))
                for point in retained
            }
            next_domain = surviving_domain(
                table,
                lambda row: tuple(
                    sorted(
                        (key, value)
                        for key, value in row.items()
                        if key not in {"region", "saturated", "generation_level", "source"}
                    )
                ) in retained_keys,
                policy=self._policy.refinement,
            )

        failure_counts: dict[str, int] = {name: 0 for name in (c.name for c in self._constraints)}
        for item in rejected:
            for name in item.failed_constraints:
                failure_counts[name] += 1

        return FeasibleRegion(
            source_table=table,
            points=tuple(retained),
            rejected=tuple(rejected),
            constraint_names=tuple(constraint.name for constraint in self._constraints),
            next_sampling_domain=next_domain,
            metadata={
                "input_point_count": len(table.points),
                "retained_point_count": len(retained),
                "rejected_point_count": len(rejected),
                "constraint_failure_counts": failure_counts,
                "correlations_preserved": True,
                "interpolation_used": False,
            },
        )
