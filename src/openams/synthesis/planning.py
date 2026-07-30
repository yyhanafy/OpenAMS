"""Immutable planning for indexed intersections of explicit circuit regions."""
from __future__ import annotations

from dataclasses import dataclass
from math import prod
from typing import Sequence

from .constraints import CircuitConstraint, FieldRelationConstraint
from .errors import InvalidRegionError
from .model import RegionInput


def _split_field(field: str) -> tuple[str, str] | None:
    if "." not in field:
        return None
    region, local = field.split(".", 1)
    if not region or not local:
        return None
    return region, local


@dataclass(frozen=True)
class JoinKey:
    """One exact equality usable as an indexed lookup key."""

    constraint_name: str
    left_region: str
    left_field: str
    right_region: str
    right_field: str

    def oriented(self, existing: frozenset[str], incoming: str) -> tuple[str, str] | None:
        """Return (existing namespaced field, incoming local field), if applicable."""
        if self.left_region in existing and self.right_region == incoming:
            return f"{self.left_region}.{self.left_field}", self.right_field
        if self.right_region in existing and self.left_region == incoming:
            return f"{self.right_region}.{self.right_field}", self.left_field
        return None


@dataclass(frozen=True)
class JoinStep:
    """Add one input region using an exact lookup key."""

    incoming_region: str
    existing_field: str
    incoming_field: str
    constraint_name: str


@dataclass(frozen=True)
class JoinPlan:
    """Deterministic plan or an explicit reason to use Cartesian fallback."""

    input_order: tuple[str, ...]
    steps: tuple[JoinStep, ...]
    indexable_constraint_names: tuple[str, ...]
    residual_constraint_names: tuple[str, ...]
    cartesian_combination_count: int
    estimated_candidate_count: int
    fallback_reason: str | None = None

    @property
    def uses_indexed_joins(self) -> bool:
        return self.fallback_reason is None and bool(self.steps)


class IntersectionPlanner:
    """Plan safe hash joins from exact cross-region equality constraints."""

    def plan(
        self,
        inputs: Sequence[RegionInput],
        constraints: Sequence[CircuitConstraint],
    ) -> JoinPlan:
        regions = tuple(inputs)
        if not regions:
            raise InvalidRegionError("intersection planning requires at least one input region")
        names = tuple(region.name for region in regions)
        if len(set(names)) != len(names):
            raise InvalidRegionError("input region names must be unique")

        possible = prod(len(region.rows) for region in regions)
        if len(regions) == 1:
            return JoinPlan(names, (), (), tuple(c.name for c in constraints), possible, possible)

        known = set(names)
        keys: list[JoinKey] = []
        residual: list[str] = []
        for constraint in constraints:
            key = self._join_key(constraint, known)
            if key is None:
                residual.append(constraint.name)
            else:
                keys.append(key)

        # Start with the smallest region to minimize the first intermediate table.
        by_name = {region.name: region for region in regions}
        start = min(regions, key=lambda region: (len(region.rows), region.name)).name
        order = [start]
        joined = frozenset({start})
        remaining = set(names) - set(joined)
        steps: list[JoinStep] = []
        used: list[str] = []
        estimate = len(by_name[start].rows)

        while remaining:
            candidates: list[tuple[int, str, JoinKey, tuple[str, str]]] = []
            for incoming in remaining:
                for key in keys:
                    oriented = key.oriented(joined, incoming)
                    if oriented is not None:
                        candidates.append((len(by_name[incoming].rows), incoming, key, oriented))
            if not candidates:
                return JoinPlan(
                    tuple(order + sorted(remaining)),
                    tuple(steps),
                    tuple(used),
                    tuple(c.name for c in constraints if c.name not in used),
                    possible,
                    possible,
                    "not all input regions are connected by exact equality constraints",
                )
            _, incoming, key, oriented = min(candidates, key=lambda item: (item[0], item[1], item[2].constraint_name))
            existing_field, incoming_field = oriented
            steps.append(JoinStep(incoming, existing_field, incoming_field, key.constraint_name))
            used.append(key.constraint_name)
            order.append(incoming)
            joined = frozenset(set(joined) | {incoming})
            remaining.remove(incoming)
            # Conservative estimate: never claim fewer than zero or more than Cartesian.
            estimate = min(possible, estimate * len(by_name[incoming].rows))

        return JoinPlan(
            tuple(order),
            tuple(steps),
            tuple(dict.fromkeys(used)),
            tuple(c.name for c in constraints if c.name not in used),
            possible,
            estimate,
        )

    @staticmethod
    def _join_key(constraint: CircuitConstraint, known_regions: set[str]) -> JoinKey | None:
        if not isinstance(constraint, FieldRelationConstraint):
            return None
        if (
            constraint.scale != 1.0
            or constraint.offset != 0.0
            or constraint.absolute_tolerance != 0.0
            or constraint.relative_tolerance != 0.0
        ):
            return None
        left = _split_field(constraint.left)
        right = _split_field(constraint.right)
        if left is None or right is None:
            return None
        left_region, left_field = left
        right_region, right_field = right
        if left_region == right_region:
            return None
        if left_region not in known_regions or right_region not in known_regions:
            return None
        return JoinKey(constraint.name, left_region, left_field, right_region, right_field)
