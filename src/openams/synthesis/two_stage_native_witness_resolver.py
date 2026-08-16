"""Memory-bounded native witness resolver for the two-stage op amp."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any, Mapping

LOOKUPS = (
    "lookup_m1", "lookup_m3", "lookup_m4", "lookup_m5",
    "lookup_m6_density", "lookup_m7_density",
)


def _provider_row_map(provider: Any) -> dict[int, Any]:
    mapping = getattr(provider, "_openams_row_by_index", None)
    if mapping is None:
        mapping = {int(row.index): row for row in provider.rows}
        setattr(provider, "_openams_row_by_index", mapping)
    return mapping


def _candidates(state: Any, lookup: str, provider: Any) -> list[tuple[Any, float, int]]:
    """Return (ForwardRow-or-old-dict, realized_width_um, match_index)."""
    raw = list(state.candidate_sets.get("__witness_lookup__" + lookup, []))
    if not raw:
        return []

    # Backward compatibility with the previous heavyweight dict capture.
    if isinstance(raw[0], dict):
        return [
            (item, float(item["realized_width_um"]), int(item.get("match_index", i)))
            for i, item in enumerate(raw)
        ]

    by_index = _provider_row_map(provider)
    result: list[tuple[Any, float, int]] = []
    for i, item in enumerate(raw):
        row_index, realized_width = item
        row = by_index.get(int(row_index))
        if row is None:
            raise ValueError(f"technology row index {row_index} not found in provider")
        result.append((row, float(realized_width), i))
    return result


def _field(candidate: tuple[Any, float, int], name: str) -> float:
    row, realized_width, _ = candidate
    if isinstance(row, dict):
        if name == "realized_width_um":
            return float(realized_width)
        return float(row[name])
    if name == "realized_width_um":
        return float(realized_width)
    if name == "characterized_width_um":
        return float(row.width_um)
    if name == "current_density_a_per_um":
        return float(row.id_a) / float(row.width_um)
    return float(getattr(row, name))


def _inside(value: float, interval: Any, tol: float = 0.0) -> bool:
    return float(interval.minimum) - tol <= float(value) <= float(interval.maximum) + tol


def _mid(interval: Any) -> float:
    return 0.5 * (float(interval.minimum) + float(interval.maximum))


def _realization(candidate: tuple[Any, float, int], *, operation_id: str, width_um: float, current_a: float) -> dict[str, Any]:
    row, _realized_width, match_index = candidate
    if isinstance(row, dict):
        saturated = bool(row.get("saturated", True))
    else:
        saturated = bool(row.saturated)
    return {
        "operation_id": operation_id,
        "match_index": int(match_index),
        "width_um": float(width_um),
        "characterized_width_um": _field(candidate, "characterized_width_um"),
        "vgs_v": _field(candidate, "vgs_v"),
        "vds_v": _field(candidate, "vds_v"),
        "vbs_v": _field(candidate, "vbs_v"),
        "vdsat_v": _field(candidate, "vdsat_v"),
        "predicted_current_a": float(current_a),
        "current_density_a_per_um": _field(candidate, "current_density_a_per_um"),
        "saturated": saturated,
    }


def resolve_native_witness(*, state: Any, plan: Mapping[str, Any], model: Mapping[str, Any], provider: Any, point_index: int) -> dict[str, Any]:
    del plan
    if state.status != "PASS":
        raise ValueError("cannot resolve witness for non-PASS state")

    candidates = {name: _candidates(state, name, provider) for name in LOOKUPS}
    missing = [name for name, rows in candidates.items() if not rows]
    if missing:
        raise ValueError("missing retained technology rows: " + ", ".join(missing))

    rules = model["project_inputs"]["design_rules"].get("technology_intersection", {})
    vtol = float(rules.get("node_voltage_tolerance_v", rules.get("voltage_tolerance_v", 0.025)))
    width_rtol = 0.05
    ratio_rtol = 0.10

    vdd = float(state.scalars["vdd_v"])
    vss = float(state.scalars["vss_v"])
    vin = float(state.scalars["vin_cm_v"])
    w1 = float(state.independent_values["w_m1_um"])
    i5 = float(state.independent_values["i_m5_a"])
    i1 = float(state.scalars["i_m1_a"])
    i3 = float(state.scalars["i_m3_a"])
    i4 = float(state.scalars["i_m4_a"])

    # M1: stream best candidate; do not materialize option lists.
    best_input = None
    for cand in candidates["lookup_m1"]:
        tail_vgs = vin - _field(cand, "vgs_v")
        tail_body = vss + abs(_field(cand, "vbs_v"))
        if abs(tail_vgs - tail_body) > vtol:
            continue
        tail = 0.5 * (tail_vgs + tail_body)
        if not _inside(tail, state.intervals["ntail_v"], vtol):
            continue
        score = abs(tail_vgs - tail_body) + abs(tail - _mid(state.intervals["ntail_v"]))
        if best_input is None or score < best_input[0]:
            best_input = (score, tail, cand)
    if best_input is None:
        raise ValueError("no correlated M1/tail realization")
    _, tail, m1 = best_input

    # M3/M4: indexed neighborhood search, not Cartesian product.
    #
    # Previous implementation checked every M3 against every M4:
    #   O(N3*N4)
    # which is ~46 million comparisons for point 0.
    #
    # Preserve exactly the same acceptance rules:
    #   |W3-W4| <= width_rtol * max(W3,W4)
    #   |VGS4-(VDD-N1)| <= vtol
    #
    # Sort M4 once by realized width and binary-search only the width region
    # that can possibly satisfy the relative-width constraint.
    m4_sorted = sorted(
        (
            _field(c, "realized_width_um"),
            _field(c, "vgs_v"),
            int(c[2]),  # unique deterministic match_index tie-breaker
            c,
        )
        for c in candidates["lookup_m4"]
    )
    m4_widths = [item[0] for item in m4_sorted]

    best_active = None
    for m3 in candidates["lookup_m3"]:
        vgs3 = _field(m3, "vgs_v")
        n1 = vdd - vgs3
        if not _inside(n1, state.intervals["n1_v"], vtol):
            continue

        w3 = _field(m3, "realized_width_um")

        # Solve |w3-w4| <= r*max(w3,w4) for a guaranteed superset:
        #   w4 >= w3*(1-r)
        #   w4 <= w3/(1-r)
        # for 0 <= r < 1.
        if not (0.0 <= width_rtol < 1.0):
            raise ValueError(f"invalid width_rtol={width_rtol}")

        width_lo = w3 * (1.0 - width_rtol)
        width_hi = w3 / (1.0 - width_rtol)

        lo = bisect_left(m4_widths, width_lo)
        hi = bisect_right(m4_widths, width_hi)

        target_vgs4 = vdd - n1  # algebraically same as vgs3

        for w4, vgs4, _row_index, m4cand in m4_sorted[lo:hi]:
            wallow = width_rtol * max(w3, w4, 1e-12)
            if abs(w3 - w4) > wallow:
                continue
            if abs(vgs4 - target_vgs4) > vtol:
                continue

            score = (
                abs(w3 - w4) / max(wallow, 1e-12)
                + abs(n1 - _mid(state.intervals["n1_v"]))
            )
            if best_active is None or score < best_active[0]:
                best_active = (
                    score,
                    n1,
                    0.5 * (w3 + w4),
                    m3,
                    m4cand,
                )

    if best_active is None:
        raise ValueError("no correlated M3/M4 realization")
    _, n1, w34, m3, m4 = best_active

    # M5/M7 share VBIAS. Sort lightweight M7 row references by VGS and only
    # inspect the small +/-vtol neighborhood for each M5 candidate.
    m7_sorted = sorted(
        ((_field(c, "vgs_v"), c) for c in candidates["lookup_m7_density"]),
        key=lambda item: item[0],
    )
    m7_vgs = [item[0] for item in m7_sorted]

    best_bias = None
    for m5 in candidates["lookup_m5"]:
        if tail - vss + vtol < _field(m5, "vdsat_v"):
            continue
        vb5 = vss + _field(m5, "vgs_v")
        if not _inside(vb5, state.intervals["vbias_v"], vtol):
            continue

        target_vgs7 = vb5 - vss
        lo = bisect_left(m7_vgs, target_vgs7 - vtol)
        hi = bisect_right(m7_vgs, target_vgs7 + vtol)
        for _vgs7, m7 in m7_sorted[lo:hi]:
            vb7 = vss + _field(m7, "vgs_v")
            vbias = 0.5 * (vb5 + vb7)
            score = abs(vb7 - vb5) + abs(vbias - _mid(state.intervals["vbias_v"]))
            if best_bias is None or score < best_bias[0]:
                best_bias = (score, vbias, m5, m7)
    if best_bias is None:
        raise ValueError("no correlated M5/M7 shared-bias realization")
    _, vbias, m5, m7 = best_bias

    w5 = _field(m5, "realized_width_um")
    if w5 <= 0:
        raise ValueError("non-positive M5 width")
    required_ratio = 2.0 * w34 / w5
    j7 = _field(m7, "current_density_a_per_um")

    # M6: stream best candidate; no second_options list.
    best_second = None
    for m6 in candidates["lookup_m6_density"]:
        n2 = vdd - _field(m6, "vgs_v")
        if not _inside(n2, state.intervals["n2_v"], vtol):
            continue
        if n2 - tail + vtol < _field(m1, "vdsat_v"):
            continue
        if vdd - n2 + vtol < _field(m4, "vdsat_v"):
            continue
        j6 = _field(m6, "current_density_a_per_um")
        if j6 <= 0 or j7 <= 0:
            continue
        ratio = j7 / j6
        rallow = ratio_rtol * max(abs(required_ratio), 1e-12)
        if abs(ratio - required_ratio) > rallow:
            continue

        w7i = state.intervals["w_m7_um"]
        w6i = state.intervals["w_m6_um"]
        lo = max(float(w7i.minimum), float(w6i.minimum) / ratio)
        hi = min(float(w7i.maximum), float(w6i.maximum) / ratio)
        if lo > hi:
            continue
        w7 = 0.5 * (lo + hi)
        w6 = ratio * w7
        i6 = j6 * w6
        i7 = j7 * w7
        if abs(i6 - i7) > max(1e-12, 1e-6 * abs(i7)):
            continue

        vout_lo = max(float(state.intervals["vout_v"].minimum), vss + _field(m7, "vdsat_v"))
        vout_hi = min(float(state.intervals["vout_v"].maximum), vdd - _field(m6, "vdsat_v"))
        if vout_lo > vout_hi:
            continue

        score = abs(ratio - required_ratio) / max(rallow, 1e-12) + abs(n2 - _mid(state.intervals["n2_v"]))
        if best_second is None or score < best_second[0]:
            best_second = (score, n2, w6, w7, 0.5 * (i6 + i7), vout_lo, vout_hi, m6)

    if best_second is None:
        raise ValueError("no correlated M6/M7 realization")
    _, n2, w6, w7, i67, vout_lo, vout_hi, m6 = best_second

    widths = {"M1": w1, "M2": w1, "M3": w34, "M4": w34, "M5": w5, "M6": float(w6), "M7": float(w7)}
    currents = {"M1": i1, "M2": i1, "M3": i3, "M4": i4, "M5": i5, "M6": float(i67), "M7": float(i67)}

    return {
        "artifact": "openams.native_dc_witness",
        "schema_version": 1,
        "status": "PASS",
        "circuit_name": "two_stage_opamp",
        "source": "generic_range_executor_compact_row_refs",
        "point_index": int(point_index),
        "i_m5_a": i5,
        "w_m1_um": w1,
        "widths_um": widths,
        "nf": {f"M{i}": 1 for i in range(1, 8)},
        "currents_a": currents,
        "nodes": {
            "vdd_v": vdd, "vss_v": vss, "inp_v": vin, "inn_v": vin,
            "ntail_v": float(tail), "n1_v": float(n1), "n2_v": float(n2), "vbias_v": float(vbias),
            "vout_min_v": float(vout_lo), "vout_max_v": float(vout_hi),
            "vout_v": 0.5 * (float(vout_lo) + float(vout_hi)),
        },
        "device_realizations": {
            "M1_M2": _realization(m1, operation_id="lookup_m1", width_um=w1, current_a=i1),
            "M3": _realization(m3, operation_id="lookup_m3", width_um=w34, current_a=i3),
            "M4": _realization(m4, operation_id="lookup_m4", width_um=w34, current_a=i4),
            "M5": _realization(m5, operation_id="lookup_m5", width_um=w5, current_a=i5),
            "M6": _realization(m6, operation_id="lookup_m6_density", width_um=w6, current_a=i67),
            "M7": _realization(m7, operation_id="lookup_m7_density", width_um=w7, current_a=i67),
        },
        "second_stage": {
            "required_w6_over_w7": float(required_ratio),
            "realized_w6_over_w7": float(w6 / w7),
            "realized_j7_over_j6": float(j7 / _field(m6, "current_density_a_per_um")),
        },
    }
