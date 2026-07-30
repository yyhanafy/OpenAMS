"""Planned indexed intersections with explicit Cartesian fallback."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .constraints import CircuitConstraint
from .errors import CombinationBudgetExceededError, InvalidRegionError
from .intersection import IntersectionPolicy, RegionIntersection
from .model import CircuitRegion, CircuitRow, RegionInput
from .planning import IntersectionPlanner, JoinPlan


@dataclass(frozen=True)
class PlannedIntersectionPolicy:
    """Controls when indexed execution may replace full Cartesian diagnostics."""

    max_cartesian_combinations: int = 1_000_000
    max_indexed_candidates: int = 1_000_000
    require_complete_rejection_diagnostics: bool = False
    fallback_on_unplannable: bool = True

    def __post_init__(self) -> None:
        if self.max_cartesian_combinations <= 0 or self.max_indexed_candidates <= 0:
            raise InvalidRegionError("intersection budgets must be positive")


class PlannedRegionIntersection:
    """Execute safe hash joins, then evaluate every declared constraint."""

    def __init__(
        self,
        constraints: Sequence[CircuitConstraint] = (),
        policy: PlannedIntersectionPolicy | None = None,
        planner: IntersectionPlanner | None = None,
    ) -> None:
        names = tuple(constraint.name for constraint in constraints)
        if len(set(names)) != len(names):
            raise InvalidRegionError("intersection constraint names must be unique")
        self._constraints = tuple(constraints)
        self._policy = policy or PlannedIntersectionPolicy()
        self._planner = planner or IntersectionPlanner()

    def plan(self, inputs: Sequence[RegionInput]) -> JoinPlan:
        return self._planner.plan(inputs, self._constraints)

    def build(self, inputs: Sequence[RegionInput]) -> CircuitRegion:
        regions = tuple(inputs)
        plan = self.plan(regions)
        fallback_reason = plan.fallback_reason
        if self._policy.require_complete_rejection_diagnostics:
            fallback_reason = fallback_reason or "complete rejection diagnostics requested"

        if fallback_reason is not None:
            if not self._policy.fallback_on_unplannable:
                raise InvalidRegionError(f"indexed intersection unavailable: {fallback_reason}")
            result = RegionIntersection(
                self._constraints,
                IntersectionPolicy(max_combinations=self._policy.max_cartesian_combinations),
            ).build(regions)
            metadata = dict(result.metadata)
            metadata.update({
                "planned_intersection": True,
                "plan_fallback_reason": fallback_reason,
                "planned_input_order": plan.input_order,
            })
            return CircuitRegion(result.inputs, result.rows, result.rejected, result.constraint_names, metadata)

        return self._build_indexed(regions, plan)

    def _build_indexed(self, regions: tuple[RegionInput, ...], plan: JoinPlan) -> CircuitRegion:
        by_name = {region.name: region for region in regions}
        start = by_name[plan.input_order[0]]
        partials: list[tuple[dict[str, Any], dict[str, int]]] = []
        for index, row in enumerate(start.rows):
            partials.append(({f"{start.name}.{field}": value for field, value in row.items()}, {start.name: index}))

        indexed_candidate_count = len(partials)
        for step in plan.steps:
            incoming = by_name[step.incoming_region]
            lookup: dict[Any, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
            for index, row in enumerate(incoming.rows):
                if step.incoming_field not in row:
                    # Preserve ordinary constraint behavior by falling back when the index field is absent.
                    return self._fallback_for_missing_field(regions, plan, step.incoming_region, step.incoming_field)
                lookup[row[step.incoming_field]].append((index, row))

            next_partials: list[tuple[dict[str, Any], dict[str, int]]] = []
            for values, indices in partials:
                if step.existing_field not in values:
                    return self._fallback_for_missing_field(regions, plan, step.existing_field, "")
                for source_index, source_row in lookup.get(values[step.existing_field], ()):
                    merged = dict(values)
                    merged.update({f"{incoming.name}.{field}": value for field, value in source_row.items()})
                    merged_indices = dict(indices)
                    merged_indices[incoming.name] = source_index
                    next_partials.append((merged, merged_indices))
                    indexed_candidate_count += 1
                    if indexed_candidate_count > self._policy.max_indexed_candidates:
                        raise CombinationBudgetExceededError(
                            f"indexed intersection produced more than {self._policy.max_indexed_candidates} candidates"
                        )
            partials = next_partials
            if not partials:
                break

        retained: list[CircuitRow] = []
        failure_counts = {constraint.name: 0 for constraint in self._constraints}
        filtered_count = 0
        for values, indices in partials:
            accepted = True
            for constraint in self._constraints:
                decision = constraint.evaluate(values)
                if not decision.accepted:
                    failure_counts[constraint.name] += 1
                    accepted = False
            if accepted:
                retained.append(CircuitRow(values, indices))
            else:
                filtered_count += 1

        possible = plan.cartesian_combination_count
        return CircuitRegion(
            inputs=regions,
            rows=tuple(retained),
            rejected=(),
            constraint_names=tuple(constraint.name for constraint in self._constraints),
            metadata={
                "candidate_combination_count": possible,
                "indexed_materialized_candidate_count": len(partials),
                "indexed_work_item_count": indexed_candidate_count,
                "retained_combination_count": len(retained),
                "rejected_combination_count": possible - len(retained),
                "post_join_filtered_candidate_count": filtered_count,
                "retained_rejection_record_count": 0,
                "constraint_failure_counts": failure_counts,
                "source_correlations_preserved": True,
                "intersection_method": "planned_indexed_equality_join",
                "interpolation_used": False,
                "planned_intersection": True,
                "planned_input_order": plan.input_order,
                "indexed_constraint_names": plan.indexable_constraint_names,
                "residual_constraint_names": plan.residual_constraint_names,
                "rejection_diagnostics_complete": False,
            },
        )

    def _fallback_for_missing_field(
        self,
        regions: tuple[RegionInput, ...],
        plan: JoinPlan,
        region: str,
        field: str,
    ) -> CircuitRegion:
        if not self._policy.fallback_on_unplannable:
            raise InvalidRegionError(f"indexed field missing: {region}.{field}".rstrip("."))
        result = RegionIntersection(
            self._constraints,
            IntersectionPolicy(max_combinations=self._policy.max_cartesian_combinations),
        ).build(regions)
        metadata = dict(result.metadata)
        metadata.update({
            "planned_intersection": True,
            "plan_fallback_reason": f"indexed field missing: {region}.{field}".rstrip("."),
            "planned_input_order": plan.input_order,
        })
        return CircuitRegion(result.inputs, result.rows, result.rejected, result.constraint_names, metadata)
