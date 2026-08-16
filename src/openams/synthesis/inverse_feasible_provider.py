"""Current-conditioned inverse-feasible technology view.

The canonical dense characterization CSV remains the source of truth.  This
module builds an in-memory index that groups saturated forward-characterization
rows into compact inverse records keyed by device identity and (W, VGS, VBS).
Each record stores the minimum characterized VDS that supports the requested
current within tolerance, plus the full characterized VDS range.
"""
from __future__ import annotations

import csv
import json
import math
import pickle
from bisect import bisect_left, bisect_right
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from openams.synthesis.generic_complete_step5 import (
    DeviceRealization,
    DeviceRequest,
    GenericStep5Error,
    _minimum_nf,
)


def _number(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            try:
                result = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(result):
                return result
    return None


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1", "true", "yes", "y", "saturation", "saturated"
    }


@dataclass(frozen=True)
class ForwardRow:
    index: int
    polarity: str
    model: str
    length_um: float
    width_um: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    id_a: float
    vdsat_v: float | None
    saturated: bool
    gm_s: float | None
    gds_s: float | None
    vth_v: float | None


class InverseFeasibleDatasetProvider:
    """Inverse feasible view over the dense forward characterization dataset.

    The provider does not interpolate or scale a characterized row to an
    arbitrary width.  It returns only characterized (W, VGS) realizations whose
    current is within the requested tolerance.  A separate fallback provider
    may be used for missing continuous points.
    """

    name = "inverse_feasible_dense_dataset"

    def __init__(self, path: Path, *, saturation_margin_v: float = 0.0, candidate_cache_max_entries: int = 4096) -> None:
        self.path = path.resolve()
        self.saturation_margin_v = float(saturation_margin_v)
        self.candidate_cache_max_entries = max(0, int(candidate_cache_max_entries))
        self.query_count = 0
        self.fallback_query_count = 0
        self.rows = self._load()

        # Current-sorted indexes prevent a full scan of the dense dataset for
        # every device request.
        self._fixed_width_index: dict[
            tuple[str, str, float, float],
            tuple[tuple[float, ...], tuple[ForwardRow, ...]],
        ] = {}
        self._current_index: dict[
            tuple[str, str, float],
            tuple[tuple[float, ...], tuple[ForwardRow, ...]],
        ] = {}
        # OPENAMS_FAST_RANGE_LOOKUP_V1
        self._range_vgs_index: dict[
            tuple[str, str, float],
            tuple[tuple[float, ...], tuple[ForwardRow, ...]],
        ] = {}

        fixed_buckets: dict[
            tuple[str, str, float, float], list[ForwardRow]
        ] = defaultdict(list)
        current_buckets: dict[
            tuple[str, str, float], list[ForwardRow]
        ] = defaultdict(list)

        for row in self.rows:
            base_key = (
                row.model,
                row.polarity,
                self._quantize(row.length_um),
            )
            current_buckets[base_key].append(row)
            fixed_buckets[
                (*base_key, self._quantize(row.width_um))
            ].append(row)

        self._current_index = {
            key: self._sorted_current_bucket(bucket)
            for key, bucket in current_buckets.items()
        }
        self._range_vgs_index = {
            key: self._sorted_vgs_bucket(bucket)
            for key, bucket in current_buckets.items()
        }
        self._fixed_width_index = {
            key: self._sorted_current_bucket(bucket)
            for key, bucket in fixed_buckets.items()
        }

        # Backtracking frequently repeats identical device requests.
        self._candidate_cache: OrderedDict[
            tuple[Any, ...], tuple[DeviceRealization, ...]
        ] = OrderedDict()
        self.candidate_cache_hit_count = 0
        self.candidate_cache_miss_count = 0
        self.candidate_cache_eviction_count = 0
        self.candidate_cache_peak_entries = 0
        self.index_row_visit_count = 0

    @staticmethod
    def _quantize(value: float) -> float:
        """Return a stable key for characterized geometry values."""

        return round(float(value), 12)

    @staticmethod
    def _sorted_current_bucket(
        rows: Sequence[ForwardRow],
    ) -> tuple[tuple[float, ...], tuple[ForwardRow, ...]]:
        ordered = tuple(sorted(rows, key=lambda item: item.id_a))
        return tuple(item.id_a for item in ordered), ordered

    @staticmethod
    def _sorted_vgs_bucket(
        rows: Sequence[ForwardRow],
    ) -> tuple[tuple[float, ...], tuple[ForwardRow, ...]]:
        ordered = tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.vgs_v,
                    item.vbs_v,
                    item.vds_v,
                    item.width_um,
                    item.id_a,
                    item.index,
                ),
            )
        )
        return tuple(item.vgs_v for item in ordered), ordered

    def range_lookup_rows(
        self,
        *,
        model: str,
        polarity: str,
        length_um: float,
        vgs_min_v: float | None = None,
        vgs_max_v: float | None = None,
    ) -> tuple[ForwardRow, ...]:
        key = (
            str(model),
            str(polarity),
            self._quantize(length_um),
        )
        indexed = self._range_vgs_index.get(key)
        if indexed is None:
            return ()
        values, rows = indexed
        left = 0 if vgs_min_v is None else bisect_left(values, float(vgs_min_v))
        right = len(rows) if vgs_max_v is None else bisect_right(values, float(vgs_max_v))
        if right < left:
            return ()
        selected = rows[left:right]
        self.index_row_visit_count += len(selected)
        return selected

    @staticmethod
    def _cache_number(
        value: float | None,
        digits: int = 12,
    ) -> float | None:
        return None if value is None else round(float(value), digits)

    def _candidate_cache_key(
        self,
        request: DeviceRequest,
        *,
        current_relative_tolerance: float,
        current_absolute_tolerance_a: float,
        voltage_tolerance_v: float,
        width_policy: Mapping[str, float | int],
        limit: int,
    ) -> tuple[Any, ...]:
        return (
            request.model,
            request.polarity,
            self._cache_number(request.length_um),
            self._cache_number(request.target_current_a, 15),
            self._cache_number(request.fixed_width_um),
            self._cache_number(request.known_vgs_v),
            self._cache_number(request.known_vds_v),
            self._cache_number(request.known_vbs_v),
            bool(request.require_saturation),
            round(float(current_relative_tolerance), 12),
            round(float(current_absolute_tolerance_a), 15),
            round(float(voltage_tolerance_v), 12),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in width_policy.items()
                )
            ),
            int(limit),
        )

    def _indexed_rows(
        self,
        request: DeviceRequest,
        allowed_current_error: float,
    ) -> tuple[ForwardRow, ...]:
        base_key = (
            request.model,
            request.polarity,
            self._quantize(request.length_um),
        )

        if request.fixed_width_um is None:
            indexed = self._current_index.get(base_key)
        else:
            indexed = self._fixed_width_index.get(
                (
                    *base_key,
                    self._quantize(request.fixed_width_um),
                )
            )

        if indexed is None:
            return ()

        current_values, rows = indexed
        lower = max(
            0.0,
            float(request.target_current_a) - allowed_current_error,
        )
        upper = (
            float(request.target_current_a) + allowed_current_error
        )
        left = bisect_left(current_values, lower)
        right = bisect_right(current_values, upper)
        selected = rows[left:right]
        self.index_row_visit_count += len(selected)
        return selected

    def _parsed_cache_path(self) -> Path:
        cache_dir = self.path.parent / ".openams_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / (self.path.name + ".inverse_feasible_rows_v1.pkl")

    def _parsed_cache_signature(self) -> tuple[Any, ...]:
        stat = self.path.stat()
        return (
            int(stat.st_size),
            int(stat.st_mtime_ns),
            round(float(self.saturation_margin_v), 12),
            1,
        )

    def _load(self) -> tuple[ForwardRow, ...]:
        cache_path = self._parsed_cache_path()
        signature = self._parsed_cache_signature()
        try:
            with cache_path.open("rb") as stream:
                payload = pickle.load(stream)
            if (
                isinstance(payload, dict)
                and payload.get("signature") == signature
                and isinstance(payload.get("rows"), tuple)
                and payload["rows"]
            ):
                self.parsed_cache_hit = True
                return payload["rows"]
        except Exception:
            pass

        self.parsed_cache_hit = False
        try:
            rows = self._load_csv_fast_pandas()
        except Exception:
            rows = self._load_csv_legacy()

        try:
            tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
            with tmp.open("wb") as stream:
                pickle.dump(
                    {"signature": signature, "rows": rows},
                    stream,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            tmp.replace(cache_path)
        except Exception:
            pass
        return rows

    def _load_csv_fast_pandas(self) -> tuple[ForwardRow, ...]:
        import pandas as pd
        header = list(pd.read_csv(self.path, nrows=0).columns)
        present = set(header)

        def choose(*names: str, required: bool = True) -> str | None:
            for name in names:
                if name in present:
                    return name
            if required:
                raise GenericStep5Error(
                    f"technology CSV missing columns {names}: {self.path}"
                )
            return None

        cols = {
            "polarity": choose("polarity"),
            "model": choose("model"),
            "length": choose("length_um", "l_um"),
            "width": choose("width_um", "w_um"),
            "vgs": choose("vgs_v", "vgs_abs_v"),
            "vds": choose("vds_v", "vds_abs_v"),
            "vbs": choose("vbs_v", "vbs_abs_v"),
            "id": choose("id_abs_a", "id_a", "id"),
            "vdsat": choose("vdsat_abs_v", "vdsat_v", "vdsat", required=False),
            "saturated": choose("saturated", required=False),
            "gm": choose("gm_s", "gm", required=False),
            "gds": choose("gds_s", "gds", required=False),
            "vth": choose("vth_abs_v", "vth_v", "vth", required=False),
        }
        usecols = [v for v in dict.fromkeys(cols.values()) if v is not None]
        frame = pd.read_csv(self.path, usecols=usecols, low_memory=False)
        records = frame.to_dict(orient="records")
        rows: list[ForwardRow] = []

        for index, raw in enumerate(records):
            try:
                length = float(raw[cols["length"]])
                width = float(raw[cols["width"]])
                vgs = float(raw[cols["vgs"]])
                vds = float(raw[cols["vds"]])
                vbs = float(raw[cols["vbs"]])
                ida = float(raw[cols["id"]])
            except (TypeError, ValueError, KeyError):
                continue
            if not all(math.isfinite(v) for v in (length, width, vgs, vds, vbs, ida)):
                continue

            vdsat = None
            if cols["vdsat"] is not None:
                try:
                    x = float(raw[cols["vdsat"]])
                    if math.isfinite(x):
                        vdsat = x
                except (TypeError, ValueError, KeyError):
                    pass

            saturated = _truth(raw[cols["saturated"]]) if cols["saturated"] is not None else True
            if vdsat is not None:
                saturated = saturated and vds >= vdsat + self.saturation_margin_v
            if not saturated:
                continue

            def optional(name: str | None) -> float | None:
                if name is None:
                    return None
                try:
                    x = float(raw[name])
                except (TypeError, ValueError, KeyError):
                    return None
                return x if math.isfinite(x) else None

            rows.append(
                ForwardRow(
                    index=index,
                    polarity=str(raw[cols["polarity"]]).strip().lower(),
                    model=str(raw[cols["model"]]).strip(),
                    length_um=length,
                    width_um=width,
                    vgs_v=abs(vgs),
                    vds_v=abs(vds),
                    vbs_v=abs(vbs),
                    id_a=abs(ida),
                    vdsat_v=abs(vdsat) if vdsat is not None else None,
                    saturated=True,
                    gm_s=optional(cols["gm"]),
                    gds_s=optional(cols["gds"]),
                    vth_v=optional(cols["vth"]),
                )
            )

        if not rows:
            raise GenericStep5Error(
                f"no saturated rows in dense technology dataset: {self.path}"
            )
        return tuple(rows)

    def _load_csv_legacy(self) -> tuple[ForwardRow, ...]:
        rows: list[ForwardRow] = []
        with self.path.open(newline="", encoding="utf-8") as stream:
            for index, raw in enumerate(csv.DictReader(stream)):
                required = {
                    "length_um": _number(raw, "length_um", "l_um"),
                    "width_um": _number(raw, "width_um", "w_um"),
                    "vgs_v": _number(raw, "vgs_v", "vgs_abs_v"),
                    "vds_v": _number(raw, "vds_v", "vds_abs_v"),
                    "vbs_v": _number(raw, "vbs_v", "vbs_abs_v"),
                    "id_a": _number(raw, "id_abs_a", "id_a", "id"),
                }
                if any(value is None for value in required.values()):
                    continue
                vdsat = _number(raw, "vdsat_abs_v", "vdsat_v", "vdsat")
                saturated = _truth(raw.get("saturated", True))
                if vdsat is not None:
                    saturated = saturated and required["vds_v"] >= vdsat + self.saturation_margin_v
                if not saturated:
                    continue
                rows.append(
                    ForwardRow(
                        index=index,
                        polarity=str(raw.get("polarity", "")).strip().lower(),
                        model=str(raw.get("model", "")).strip(),
                        length_um=float(required["length_um"]),
                        width_um=float(required["width_um"]),
                        vgs_v=abs(float(required["vgs_v"])),
                        vds_v=abs(float(required["vds_v"])),
                        vbs_v=abs(float(required["vbs_v"])),
                        id_a=abs(float(required["id_a"])),
                        vdsat_v=abs(vdsat) if vdsat is not None else None,
                        saturated=True,
                        gm_s=_number(raw, "gm_s", "gm"),
                        gds_s=_number(raw, "gds_s", "gds"),
                        vth_v=_number(raw, "vth_abs_v", "vth_v", "vth"),
                    )
                )
        if not rows:
            raise GenericStep5Error(f"no saturated rows in dense technology dataset: {self.path}")
        return tuple(rows)

    def candidates(
        self,
        request: DeviceRequest,
        *,
        current_relative_tolerance: float,
        current_absolute_tolerance_a: float,
        voltage_tolerance_v: float,
        width_policy: Mapping[str, float | int],
        limit: int,
    ) -> Sequence[DeviceRealization]:
        self.query_count += 1

        cache_key = self._candidate_cache_key(
            request,
            current_relative_tolerance=current_relative_tolerance,
            current_absolute_tolerance_a=current_absolute_tolerance_a,
            voltage_tolerance_v=voltage_tolerance_v,
            width_policy=width_policy,
            limit=limit,
        )
        cached = self._candidate_cache.get(cache_key)
        if cached is not None:
            self.candidate_cache_hit_count += 1
            self._candidate_cache.move_to_end(cache_key)
            return list(cached)
        self.candidate_cache_miss_count += 1

        allowed_current_error = max(
            current_absolute_tolerance_a,
            current_relative_tolerance
            * max(abs(request.target_current_a), 1e-30),
        )
        rows = self._indexed_rows(
            request,
            allowed_current_error,
        )

        grouped: dict[
            tuple[float, float, float], list[ForwardRow]
        ] = defaultdict(list)

        for row in rows:
            # Width equality is already enforced by the fixed-width index.
            if (
                request.known_vgs_v is not None
                and abs(row.vgs_v - request.known_vgs_v)
                > voltage_tolerance_v
            ):
                continue
            if (
                request.known_vbs_v is not None
                and abs(row.vbs_v - request.known_vbs_v)
                > voltage_tolerance_v
            ):
                continue
            if (
                request.known_vds_v is not None
                and request.known_vds_v + voltage_tolerance_v
                < row.vds_v
            ):
                # The characterized row's VDS is a sufficient saturated VDS.
                # A known circuit VDS below it cannot use this row.
                continue
            # Quantize the physical tuple so numerically equivalent rows from
            # different VDS samples collapse into one inverse-feasible region.
            grouped[
                (
                    self._quantize(row.width_um),
                    self._quantize(row.vgs_v),
                    self._quantize(row.vbs_v),
                )
            ].append(row)

        scored: list[
            tuple[
                tuple[float, float, float, float],
                DeviceRealization,
            ]
        ] = []

        for (width_um, vgs_v, vbs_v), support in grouped.items():
            nf = _minimum_nf(width_um, width_policy)
            if nf is None:
                continue

            best = min(
                support,
                key=lambda row: abs(
                    row.id_a - request.target_current_a
                ),
            )
            min_vds = min(row.vds_v for row in support)
            max_vds = max(row.vds_v for row in support)
            supporting_vdsat = [
                row.vdsat_v for row in support
                if row.vdsat_v is not None
            ]
            min_vdsat = (
                min(supporting_vdsat)
                if supporting_vdsat else None
            )
            max_vdsat = (
                max(supporting_vdsat)
                if supporting_vdsat else None
            )
            supporting_indices = sorted({row.index for row in support})
            current_error = abs(
                best.id_a - request.target_current_a
            )
            vgs_error = (
                abs(vgs_v - request.known_vgs_v)
                if request.known_vgs_v is not None
                else 0.0
            )
            vbs_error = (
                abs(vbs_v - request.known_vbs_v)
                if request.known_vbs_v is not None
                else 0.0
            )

            realization = DeviceRealization(
                width_um=width_um,
                nf=nf,
                finger_width_um=width_um / nf,
                predicted_current_a=best.id_a,
                vgs_v=vgs_v,
                vds_v=min_vds,
                vbs_v=vbs_v,
                # Use the worst-case VDSAT over the entire feasible tuple so
                # headroom screening is conservative and deterministic.
                vdsat_v=max_vdsat,
                saturated=True,
                provenance={
                    "provider": self.name,
                    "technology_source": str(self.path),
                    # The representative row is retained only for tracing;
                    # it is not part of the physical-region identity.
                    "technology_row_index": best.index,
                    "supporting_row_indices": supporting_indices,
                    "supporting_row_count": len(support),
                    "minimum_saturated_vds_v": min_vds,
                    "maximum_characterized_vds_v": max_vds,
                    "minimum_vdsat_v": min_vdsat,
                    "maximum_vdsat_v": max_vdsat,
                    "current_absolute_error_a": current_error,
                    "current_relative_error": (
                        current_error
                        / max(
                            abs(request.target_current_a),
                            1e-30,
                        )
                    ),
                    "maximum_voltage_mismatch_v": max(
                        vgs_error,
                        vbs_error,
                    ),
                    "gm_s": best.gm_s,
                    "gds_s": best.gds_s,
                    "vth_v": best.vth_v,
                    "inverse_tuple": True,
                },
            )
            scored.append(
                (
                    (
                        current_error
                        / max(
                            abs(request.target_current_a),
                            1e-30,
                        ),
                        max(vgs_error, vbs_error),
                        min_vds,
                        width_um,
                    ),
                    realization,
                )
            )

        scored.sort(key=lambda item: item[0])
        result = tuple(
            item[1]
            for item in scored[:limit]
        )
        if self.candidate_cache_max_entries > 0:
            self._candidate_cache[cache_key] = result
            self._candidate_cache.move_to_end(cache_key)
            while len(self._candidate_cache) > self.candidate_cache_max_entries:
                self._candidate_cache.popitem(last=False)
                self.candidate_cache_eviction_count += 1
            self.candidate_cache_peak_entries = max(
                self.candidate_cache_peak_entries,
                len(self._candidate_cache),
            )
        return list(result)


def _request_cache_key(request: DeviceRequest) -> tuple[Any, ...]:
    def q(value: float | None) -> float | None:
        return None if value is None else round(float(value), 12)
    return (
        request.model, request.polarity, q(request.length_um),
        q(request.target_current_a), q(request.fixed_width_um),
        q(request.known_vgs_v), q(request.known_vds_v),
        q(request.known_vbs_v), bool(request.require_saturation),
    )


def _q(value: float | None, digits: int = 12) -> float | None:
    return None if value is None else round(float(value), digits)


def _physical_realization_key(item: DeviceRealization) -> tuple[Any, ...]:
    provenance = item.provenance
    return (
        _q(item.width_um),
        _q(item.vgs_v),
        _q(item.vbs_v),
        _q(provenance.get("minimum_saturated_vds_v", item.vds_v)),
        _q(provenance.get("maximum_characterized_vds_v", item.vds_v)),
    )


def _collapse_realizations(
    items: Sequence[DeviceRealization],
) -> list[DeviceRealization]:
    """Collapse equivalent rows into one conservative feasible region."""

    grouped: dict[tuple[Any, ...], list[DeviceRealization]] = defaultdict(list)
    for item in items:
        grouped[_physical_realization_key(item)].append(item)

    result: list[DeviceRealization] = []
    for group in grouped.values():
        best = min(
            group,
            key=lambda item: float(
                item.provenance.get("current_absolute_error_a", 0.0)
            ),
        )
        vdsat_values = [
            float(item.vdsat_v) for item in group
            if item.vdsat_v is not None
        ]
        provenance = dict(best.provenance)
        all_indices: set[int] = set()
        for item in group:
            raw = item.provenance.get("supporting_row_indices")
            if isinstance(raw, (list, tuple)):
                all_indices.update(int(value) for value in raw)
            elif item.provenance.get("technology_row_index") is not None:
                all_indices.add(int(item.provenance["technology_row_index"]))
        provenance.update({
            "supporting_row_indices": sorted(all_indices),
            "supporting_row_count": max(
                int(provenance.get("supporting_row_count", 0)),
                len(all_indices),
            ),
            "minimum_vdsat_v": min(vdsat_values) if vdsat_values else None,
            "maximum_vdsat_v": max(vdsat_values) if vdsat_values else None,
            "collapsed_equivalent_realization_count": len(group),
        })
        result.append(DeviceRealization(
            width_um=best.width_um,
            nf=best.nf,
            finger_width_um=best.finger_width_um,
            predicted_current_a=best.predicted_current_a,
            vgs_v=best.vgs_v,
            vds_v=best.vds_v,
            vbs_v=best.vbs_v,
            vdsat_v=max(vdsat_values) if vdsat_values else None,
            saturated=all(item.saturated for item in group),
            provenance=provenance,
        ))
    return result


class HybridInverseFeasibleProvider:
    """Dense inverse index with targeted fallback and persistent cache."""

    name = "inverse_feasible_dense_dataset_with_mlp_fallback"

    def __init__(self, path: Path, *, fallback_provider: Any | None = None,
                 adaptive_cache_path: Path | None = None,
                 saturation_margin_v: float = 0.0) -> None:
        self.primary = InverseFeasibleDatasetProvider(
            path, saturation_margin_v=saturation_margin_v
        )
        self.path = self.primary.path
        self.fallback_provider = fallback_provider
        self.adaptive_cache_path = (
            adaptive_cache_path.resolve() if adaptive_cache_path is not None else None
        )
        self._adaptive: dict[tuple[Any, ...], tuple[DeviceRealization, ...]] = {}
        self.primary_hit_count = 0
        self.cache_hit_count = 0
        self.fallback_request_count = 0
        self.fallback_result_count = 0
        if self.adaptive_cache_path is not None and self.adaptive_cache_path.is_file():
            self._load_adaptive_cache()

    @property
    def query_count(self) -> int:
        return int(self.primary.query_count)

    @property
    def fallback_query_count(self) -> int:
        return int(getattr(self.fallback_provider, "query_count", 0))

    def flush(self) -> None:
        flush = getattr(self.fallback_provider, "flush", None)
        if callable(flush):
            flush()

    def _load_adaptive_cache(self) -> None:
        assert self.adaptive_cache_path is not None
        grouped: dict[tuple[Any, ...], list[DeviceRealization]] = defaultdict(list)
        with self.adaptive_cache_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                try:
                    key = tuple(json.loads(row["request_key_json"]))
                    provenance = json.loads(row.get("provenance_json") or "{}")
                    grouped[key].append(DeviceRealization(
                        width_um=float(row["width_um"]), nf=int(row["nf"]),
                        finger_width_um=float(row["finger_width_um"]),
                        predicted_current_a=float(row["predicted_current_a"]),
                        vgs_v=float(row["vgs_v"]), vds_v=float(row["vds_v"]),
                        vbs_v=float(row["vbs_v"]),
                        vdsat_v=None if row.get("vdsat_v", "") == "" else float(row["vdsat_v"]),
                        saturated=_truth(row.get("saturated", True)),
                        provenance=provenance,
                    ))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        self._adaptive = {key: tuple(items) for key, items in grouped.items()}

    def _persist(self, key: tuple[Any, ...], items: Sequence[DeviceRealization]) -> None:
        if self.adaptive_cache_path is None or not items:
            return
        self.adaptive_cache_path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["request_key_json", "width_um", "nf", "finger_width_um",
                  "predicted_current_a", "vgs_v", "vds_v", "vbs_v",
                  "vdsat_v", "saturated", "provenance_json"]
        header = not self.adaptive_cache_path.exists() or self.adaptive_cache_path.stat().st_size == 0
        with self.adaptive_cache_path.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            if header:
                writer.writeheader()
            for item in items:
                writer.writerow({
                    "request_key_json": json.dumps(list(key), separators=(",", ":")),
                    "width_um": item.width_um, "nf": item.nf,
                    "finger_width_um": item.finger_width_um,
                    "predicted_current_a": item.predicted_current_a,
                    "vgs_v": item.vgs_v, "vds_v": item.vds_v,
                    "vbs_v": item.vbs_v,
                    "vdsat_v": "" if item.vdsat_v is None else item.vdsat_v,
                    "saturated": item.saturated,
                    "provenance_json": json.dumps(dict(item.provenance), default=str, separators=(",", ":")),
                })

    def candidates(self, request: DeviceRequest, **kwargs: Any) -> Sequence[DeviceRealization]:
        primary = _collapse_realizations(
            self.primary.candidates(request, **kwargs)
        )
        if primary:
            self.primary_hit_count += 1
            return primary[: int(kwargs.get("limit", len(primary)))]
        key = _request_cache_key(request)
        cached = self._adaptive.get(key, ())
        if cached:
            self.cache_hit_count += 1
            collapsed = _collapse_realizations(cached)
            return collapsed[: int(kwargs.get("limit", len(collapsed)))]
        if self.fallback_provider is None:
            return []
        self.fallback_request_count += 1
        fallback = _collapse_realizations(
            list(self.fallback_provider.candidates(request, **kwargs))
        )
        if not fallback:
            return []
        tagged: list[DeviceRealization] = []
        for item in fallback:
            provenance = dict(item.provenance)
            provenance.update({
                "provider": self.name,
                "realization_source": "direct_mlp_fallback",
                "canonical_technology_source": str(self.path),
                "adaptive_cache": str(self.adaptive_cache_path) if self.adaptive_cache_path else None,
                "exact_requested_width_um": request.fixed_width_um,
            })
            tagged.append(DeviceRealization(
                width_um=item.width_um, nf=item.nf, finger_width_um=item.finger_width_um,
                predicted_current_a=item.predicted_current_a, vgs_v=item.vgs_v,
                vds_v=item.vds_v, vbs_v=item.vbs_v, vdsat_v=item.vdsat_v,
                saturated=item.saturated, provenance=provenance,
            ))
        self._adaptive[key] = tuple(tagged)
        self.fallback_result_count += len(tagged)
        self._persist(key, tagged)
        return tagged
