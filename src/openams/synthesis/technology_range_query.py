"""Generic indexed range queries over OpenAMS forward technology rows.

This module is deliberately topology agnostic.  It knows only immutable device
identity (model, polarity, L) and generic MOS row coordinates.  It provides
exact *prefiltering*: callers must still apply their original constraints to
returned rows, so using this index cannot broaden or narrow final semantics.

Currently indexed continuous coordinates:
  - VGS magnitude
  - current density J = |Id| / W
  - characterized drain current |Id|

The engine automatically chooses the index producing the smallest candidate
slice for the supplied bounds.  Additional indexes can be added later without
changing circuit plans or callers.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class NumericBounds:
    minimum: float | None = None
    maximum: float | None = None

    def normalized(self) -> "NumericBounds":
        lo = None if self.minimum is None else float(self.minimum)
        hi = None if self.maximum is None else float(self.maximum)
        return NumericBounds(lo, hi)


@dataclass(frozen=True)
class RangeQuery:
    model: str
    polarity: str
    length_um: float
    vgs_v: NumericBounds | None = None
    current_density_a_per_um: NumericBounds | None = None
    id_a: NumericBounds | None = None


@dataclass(frozen=True)
class QueryStats:
    index_name: str
    base_row_count: int
    candidate_row_count: int


@dataclass(frozen=True)
class _SortedIndex:
    values: tuple[float, ...]
    rows: tuple[Any, ...]

    def slice(self, bounds: NumericBounds | None) -> tuple[Any, ...]:
        if bounds is None:
            return self.rows
        bounds = bounds.normalized()
        left = 0 if bounds.minimum is None else bisect_left(self.values, bounds.minimum)
        right = len(self.rows) if bounds.maximum is None else bisect_right(self.values, bounds.maximum)
        if right <= left:
            return ()
        return self.rows[left:right]

    def slice_count(self, bounds: NumericBounds | None) -> int:
        if bounds is None:
            return len(self.rows)
        bounds = bounds.normalized()
        left = 0 if bounds.minimum is None else bisect_left(self.values, bounds.minimum)
        right = len(self.rows) if bounds.maximum is None else bisect_right(self.values, bounds.maximum)
        return max(0, right - left)


class TechnologyRangeIndex:
    """Exact generic prefilter indexes over a provider's ForwardRow objects."""

    def __init__(self, rows: Sequence[Any]) -> None:
        buckets: dict[tuple[str, str, float], list[Any]] = {}
        for row in rows:
            key = self._base_key(row.model, row.polarity, row.length_um)
            buckets.setdefault(key, []).append(row)

        self._base_rows: dict[tuple[str, str, float], tuple[Any, ...]] = {}
        self._vgs: dict[tuple[str, str, float], _SortedIndex] = {}
        self._density: dict[tuple[str, str, float], _SortedIndex] = {}
        self._current: dict[tuple[str, str, float], _SortedIndex] = {}

        for key, bucket in buckets.items():
            base = tuple(bucket)
            self._base_rows[key] = base
            self._vgs[key] = self._build(base, lambda row: float(row.vgs_v))
            self._density[key] = self._build(
                base,
                lambda row: float(row.id_a) / float(row.width_um),
            )
            self._current[key] = self._build(base, lambda row: float(row.id_a))

        self.query_count = 0
        self.rows_returned = 0
        self.index_use_count: dict[str, int] = {
            "vgs": 0,
            "current_density": 0,
            "current": 0,
            "base": 0,
        }

    @staticmethod
    def _q(value: float) -> float:
        return round(float(value), 12)

    @classmethod
    def _base_key(cls, model: str, polarity: str, length_um: float) -> tuple[str, str, float]:
        return str(model), str(polarity), cls._q(length_um)

    @staticmethod
    def _build(rows: Iterable[Any], value_fn) -> _SortedIndex:
        ordered = tuple(
            sorted(
                rows,
                key=lambda row: (
                    float(value_fn(row)),
                    int(row.index),
                ),
            )
        )
        return _SortedIndex(
            values=tuple(float(value_fn(row)) for row in ordered),
            rows=ordered,
        )

    def query(self, query: RangeQuery) -> tuple[tuple[Any, ...], QueryStats]:
        self.query_count += 1
        key = self._base_key(query.model, query.polarity, query.length_um)
        base = self._base_rows.get(key, ())
        if not base:
            stats = QueryStats("base", 0, 0)
            return (), stats

        options: list[tuple[int, str, _SortedIndex, NumericBounds | None]] = []
        if query.vgs_v is not None:
            index = self._vgs[key]
            options.append((index.slice_count(query.vgs_v), "vgs", index, query.vgs_v))
        if query.current_density_a_per_um is not None:
            index = self._density[key]
            options.append((
                index.slice_count(query.current_density_a_per_um),
                "current_density",
                index,
                query.current_density_a_per_um,
            ))
        if query.id_a is not None:
            index = self._current[key]
            options.append((index.slice_count(query.id_a), "current", index, query.id_a))

        if options:
            # Every supplied bound is mandatory. Intersect all indexed slices,
            # beginning with the smallest slice to minimize work.
            options.sort(key=lambda item: (item[0], item[1]))
            _count, first_name, first_index, first_bounds = options[0]
            rows = first_index.slice(first_bounds)

            used_names = [first_name]
            if len(options) > 1 and rows:
                row_ids = {int(row.index) for row in rows}
                for _count, other_name, other_index, other_bounds in options[1:]:
                    allowed = {
                        int(row.index)
                        for row in other_index.slice(other_bounds)
                    }
                    row_ids.intersection_update(allowed)
                    used_names.append(other_name)
                    if not row_ids:
                        break
                rows = tuple(row for row in rows if int(row.index) in row_ids)

            name = "+".join(used_names)
        else:
            name = "base"
            rows = base

        # Keep aggregate accounting by component index names.
        if name == "base":
            self.index_use_count["base"] += 1
        else:
            for component in name.split("+"):
                self.index_use_count[component] += 1

        self.rows_returned += len(rows)
        return tuple(rows), QueryStats(name, len(base), len(rows))


def get_or_build_range_index(provider: Any) -> TechnologyRangeIndex:
    """Attach one lazy range index to any provider exposing ``rows``."""
    index = getattr(provider, "_openams_technology_range_index", None)
    if index is None:
        index = TechnologyRangeIndex(provider.rows)
        setattr(provider, "_openams_technology_range_index", index)
    return index
