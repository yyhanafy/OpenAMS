"""Ordered folded-cascode DC design-space propagation.

Evaluates every independent (W1, I3) point once and writes one PASS/FAIL
record per point. It never calls the legacy recursive Step-5 solver.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from openams.synthesis.generic_complete_step5 import (
    DeviceRealization,
    DeviceRequest,
    _device_map,
    _minimum_nf,
    _polarity,
    _width_policy,
)
from openams.synthesis.inverse_feasible_provider import InverseFeasibleDatasetProvider


class OrderedPropagationError(ValueError):
    pass


@dataclass(frozen=True)
class Interval:
    minimum: float
    maximum: float

    def valid(self, tolerance: float = 0.0) -> bool:
        return self.minimum <= self.maximum + tolerance


NODE_NAMES = (
    "vdd", "vss", "vip", "vin", "tail", "psrc_left", "psrc_right",
    "x", "nsink_left", "nsink_right", "vnb1_node", "vpb1_node",
    "vnb2_node", "vpb2_node", "vout",
)

LOOKUP_COUNT_FIELDS = (
    "input_pair_candidate_count", "m3_candidate_count",
    "upper_pair_candidate_count", "lower_sink_candidate_count",
    "nmos_cascode_candidate_count", "folded_pmos_candidate_count",
)


def _linspace(minimum: float, maximum: float, count: int) -> list[float]:
    if count <= 0:
        raise OrderedPropagationError("sample count must be positive")
    if count == 1:
        return [0.5 * (minimum + maximum)]
    step = (maximum - minimum) / (count - 1)
    return [minimum + index * step for index in range(count)]


def _numeric_operating_conditions(model: Mapping[str, Any]) -> dict[str, float]:
    raw = model["project_inputs"]["design_rules"].get("operating_conditions", {})
    result = {
        str(key): float(value)
        for key, value in raw.items()
        if isinstance(value, (int, float))
    }
    required = ("vdd_v", "vss_v", "vin_cm_v")
    missing = [key for key in required if key not in result]
    if missing:
        raise OrderedPropagationError(f"missing operating conditions: {missing}")
    return result


def _technology_tolerances(model: Mapping[str, Any]) -> dict[str, float]:
    raw = model["project_inputs"]["design_rules"].get("technology_intersection", {})
    return {
        "current_relative_tolerance": float(
            raw.get("current_relative_tolerance", raw.get("current_rel_tolerance", 0.10))
        ),
        "current_absolute_tolerance_a": float(
            raw.get("current_absolute_tolerance_a", raw.get("current_abs_tolerance_a", 1e-6))
        ),
        "voltage_tolerance_v": float(
            raw.get("node_voltage_tolerance_v", raw.get("voltage_tolerance_v", 0.025))
        ),
    }


def _device_request(
    model: Mapping[str, Any],
    device_name: str,
    *,
    target_current_a: float,
    fixed_width_um: float | None,
    known_vgs_v: float | None = None,
    known_vds_v: float | None = None,
    known_vbs_v: float | None = None,
) -> DeviceRequest:
    devices = _device_map(model)
    device = devices[device_name.upper()]
    rules = model["project_inputs"]["design_rules"]["device_constraints"]["all_mos"]
    return DeviceRequest(
        device=device_name.upper(),
        model=str(device["model"]),
        polarity=_polarity(str(device["model"])),
        length_um=float(rules["length_um"]),
        target_current_a=float(target_current_a),
        fixed_width_um=None if fixed_width_um is None else float(fixed_width_um),
        known_vgs_v=known_vgs_v,
        known_vds_v=known_vds_v,
        known_vbs_v=known_vbs_v,
        require_saturation=True,
    )


def _query(
    provider: InverseFeasibleDatasetProvider,
    model: Mapping[str, Any],
    request: DeviceRequest,
    *,
    limit: int,
) -> list[DeviceRealization]:
    tol = _technology_tolerances(model)
    return list(
        provider.candidates(
            request,
            current_relative_tolerance=tol["current_relative_tolerance"],
            current_absolute_tolerance_a=tol["current_absolute_tolerance_a"],
            voltage_tolerance_v=tol["voltage_tolerance_v"],
            width_policy=_width_policy(model),
            limit=limit,
        )
    )



def _query_scaled_fixed_width(
    provider: InverseFeasibleDatasetProvider,
    model: Mapping[str, Any],
    request: DeviceRequest,
    *,
    limit: int,
) -> list[DeviceRealization]:
    """Realize an exact requested total width by linear current scaling.

    The dense dataset supplies characterized voltage tuples and current
    density. The independent total width remains exact and is not required
    to equal one of the characterized dataset widths.
    """

    if request.fixed_width_um is None:
        raise OrderedPropagationError(
            "scaled fixed-width lookup requires fixed_width_um"
        )

    tolerances = _technology_tolerances(model)
    relative_tolerance = tolerances[
        "current_relative_tolerance"
    ]
    absolute_tolerance = tolerances[
        "current_absolute_tolerance_a"
    ]

    allowed_error = max(
        absolute_tolerance,
        relative_tolerance
        * max(abs(request.target_current_a), 1e-30),
    )

    width_policy = _width_policy(model)
    nf = _minimum_nf(
        float(request.fixed_width_um),
        width_policy,
    )
    if nf is None:
        return []

    grouped: dict[
        tuple[float, float],
        list[Any],
    ] = {}

    for row in provider.rows:
        if row.model != request.model:
            continue
        if row.polarity != request.polarity:
            continue
        if not math.isclose(
            row.length_um,
            request.length_um,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            continue

        if row.width_um <= 0.0:
            continue

        predicted_current = (
            row.id_a
            / row.width_um
            * float(request.fixed_width_um)
        )

        if (
            abs(predicted_current - request.target_current_a)
            > allowed_error
        ):
            continue

        if (
            request.known_vgs_v is not None
            and abs(row.vgs_v - request.known_vgs_v)
            > tolerances["voltage_tolerance_v"]
        ):
            continue

        if (
            request.known_vbs_v is not None
            and abs(row.vbs_v - request.known_vbs_v)
            > tolerances["voltage_tolerance_v"]
        ):
            continue

        key = (
            round(float(row.vgs_v), 12),
            round(float(row.vbs_v), 12),
        )
        grouped.setdefault(key, []).append(
            (row, predicted_current)
        )

    realizations: list[
        tuple[tuple[float, float, float], DeviceRealization]
    ] = []

    for (_vgs_key, _vbs_key), support in grouped.items():
        best_row, best_current = min(
            support,
            key=lambda item: abs(
                item[1] - request.target_current_a
            ),
        )

        vdsat_values = [
            float(row.vdsat_v)
            for row, _current in support
            if row.vdsat_v is not None
        ]
        if not vdsat_values:
            continue

        minimum_vds = min(
            float(row.vds_v)
            for row, _current in support
        )
        maximum_vds = max(
            float(row.vds_v)
            for row, _current in support
        )
        maximum_vdsat = max(vdsat_values)

        current_error = abs(
            best_current - request.target_current_a
        )

        realization = DeviceRealization(
            width_um=float(request.fixed_width_um),
            nf=nf,
            finger_width_um=(
                float(request.fixed_width_um) / nf
            ),
            predicted_current_a=float(best_current),
            vgs_v=float(best_row.vgs_v),
            vds_v=minimum_vds,
            vbs_v=float(best_row.vbs_v),
            vdsat_v=maximum_vdsat,
            saturated=True,
            provenance={
                "provider": (
                    "inverse_feasible_density_scaled_width"
                ),
                "technology_source": str(provider.path),
                "scaling_model": "linear_current_density",
                "characterized_width_um": (
                    float(best_row.width_um)
                ),
                "requested_width_um": (
                    float(request.fixed_width_um)
                ),
                "minimum_saturated_vds_v": minimum_vds,
                "maximum_characterized_vds_v": maximum_vds,
                "maximum_vdsat_v": maximum_vdsat,
                "current_absolute_error_a": current_error,
                "current_relative_error": (
                    current_error
                    / max(
                        abs(request.target_current_a),
                        1e-30,
                    )
                ),
            },
        )

        realizations.append(
            (
                (
                    current_error
                    / max(
                        abs(request.target_current_a),
                        1e-30,
                    ),
                    float(best_row.vgs_v),
                    float(best_row.vbs_v),
                ),
                realization,
            )
        )

    realizations.sort(key=lambda item: item[0])
    return [
        item[1]
        for item in realizations[:limit]
    ]


def _interval(values: Iterable[float]) -> Interval | None:
    items = [float(value) for value in values if math.isfinite(float(value))]
    if not items:
        return None
    return Interval(min(items), max(items))


def _set_interval(record: dict[str, Any], node: str, interval: Interval | None) -> None:
    record[f"{node}_min_v"] = None if interval is None else interval.minimum
    record[f"{node}_max_v"] = None if interval is None else interval.maximum


def _empty_record(
    point_index: int,
    w1: float,
    i3: float,
    operating: Mapping[str, float],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "point_index": point_index,
        "w_m1_um": float(w1),
        "i_m3_a": float(i3),
        "status": "FAIL",
        "failure_operation": None,
        "failure_reason": None,
        "last_completed_operation": None,
    }
    for field in LOOKUP_COUNT_FIELDS:
        record[field] = 0
    for node in NODE_NAMES:
        record[f"{node}_min_v"] = None
        record[f"{node}_max_v"] = None
    fixed = {
        "vdd": operating["vdd_v"],
        "vss": operating["vss_v"],
        "vip": operating["vin_cm_v"],
        "vin": operating["vin_cm_v"],
    }
    for node, value in fixed.items():
        _set_interval(record, node, Interval(value, value))
    return record


def _fail(record: dict[str, Any], operation: str, reason: str) -> dict[str, Any]:
    record["status"] = "FAIL"
    record["failure_operation"] = operation
    record["failure_reason"] = reason
    return record


def _candidate_summary(
    record: dict[str, Any],
    prefix: str,
    realizations: Sequence[DeviceRealization],
) -> None:
    if not realizations:
        return
    fields = (
        ("width_um", [item.width_um for item in realizations]),
        ("vgs_v", [item.vgs_v for item in realizations]),
        ("vdsat_v", [item.vdsat_v for item in realizations if item.vdsat_v is not None]),
        ("vbs_v", [item.vbs_v for item in realizations]),
    )
    for suffix, values in fields:
        interval = _interval(values)
        if interval is not None:
            record[f"{prefix}_{suffix}_min"] = interval.minimum
            record[f"{prefix}_{suffix}_max"] = interval.maximum



def _realization_payload(item: DeviceRealization) -> dict[str, Any]:
    """Serialize one technology-conditioned device realization."""
    return {
        "width_um": float(item.width_um),
        "nf": int(item.nf),
        "finger_width_um": float(item.finger_width_um),
        "predicted_current_a": float(item.predicted_current_a),
        "vgs_v": float(item.vgs_v),
        "vds_v": float(item.vds_v),
        "vbs_v": float(item.vbs_v),
        "vdsat_v": None if item.vdsat_v is None else float(item.vdsat_v),
        "saturated": bool(item.saturated),
        "provenance": dict(item.provenance),
    }


def _matching_input_candidate(
    input_candidates: Sequence[tuple[DeviceRealization, float, float]],
    *,
    tail_v: float,
    psrc_lower_v: float,
    voltage_tolerance_v: float,
) -> DeviceRealization:
    """Recover the M1 realization that generated one m3_by_tail state."""
    matches = [
        item
        for item, tail, psrc_lower in input_candidates
        if math.isclose(tail, tail_v, rel_tol=0.0, abs_tol=voltage_tolerance_v)
        and math.isclose(
            psrc_lower,
            psrc_lower_v,
            rel_tol=0.0,
            abs_tol=voltage_tolerance_v,
        )
    ]
    if not matches:
        raise OrderedPropagationError(
            "internal witness error: no input realization matches selected M3/tail state"
        )
    # Deterministic: prefer smallest current error, then smaller VDSAT.
    return min(
        matches,
        key=lambda item: (
            abs(float(item.predicted_current_a)),
            float(item.vdsat_v or 0.0),
            float(item.vgs_v),
        ),
    )


def _select_native_witness(
    *,
    point_index: int,
    w1_um: float,
    i3_a: float,
    vdd_v: float,
    vss_v: float,
    vin_v: float,
    voltage_tolerance_v: float,
    input_candidates: Sequence[tuple[DeviceRealization, float, float]],
    m3_by_tail: Sequence[tuple[DeviceRealization, float, float, float]],
    upper_candidates: Sequence[DeviceRealization],
    final_states: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose one native witness from the exact states used to declare PASS.

    No new technology lookup or combinatorial search is performed.  The
    selection is intentionally linear in the already-computed state lists.
    """

    if not final_states:
        raise OrderedPropagationError(
            "internal witness error: PASS point has no final states"
        )

    def final_local_margin(final: Mapping[str, Any]) -> tuple[float, tuple[float, ...]]:
        psrc = float(final["psrc_v"])
        x = float(final["x_v"])
        nsink = float(final["nsink_v"])
        vout_lo = float(final["vout_min_v"])
        vout_hi = float(final["vout_max_v"])
        m6 = final["m6"]
        m8 = final["m8"]
        m10 = final["m10"]
        vout = 0.5 * (vout_lo + vout_hi)
        margins = (
            psrc - x - float(m6.vdsat_v or 0.0),
            x - nsink - float(m8.vdsat_v or 0.0),
            nsink - vss_v - float(m10.vdsat_v or 0.0),
            psrc - vout - float(m6.vdsat_v or 0.0),
            vout - nsink - float(m8.vdsat_v or 0.0),
        )
        # Maximize the weakest already-correlated lower/folded/output margin.
        # Tie-break toward a wider output window, then deterministic scalars.
        tie = (
            vout_hi - vout_lo,
            -float(m6.width_um),
            -float(m8.width_um),
            -float(m10.width_um),
            -psrc, -x, -nsink,
        )
        return min(margins), tie

    selected_final = max(final_states, key=final_local_margin)
    psrc = float(selected_final["psrc_v"])
    x = float(selected_final["x_v"])
    nsink = float(selected_final["nsink_v"])
    vnb2 = float(selected_final["vnb2_node_v"])
    vpb2 = float(selected_final["vpb2_node_v"])
    vout_lo = float(selected_final["vout_min_v"])
    vout_hi = float(selected_final["vout_max_v"])
    m6 = selected_final["m6"]
    m8 = selected_final["m8"]
    m10 = selected_final["m10"]

    compatible_m3 = [
        item
        for item in m3_by_tail
        if float(item[3]) <= psrc + voltage_tolerance_v
    ]
    if not compatible_m3:
        raise OrderedPropagationError(
            "internal witness error: selected final state has no compatible M1/M3 state"
        )
    m3_state = max(
        compatible_m3,
        key=lambda item: (
            psrc - float(item[3]),
            -abs(float(item[0].predicted_current_a) - i3_a),
            -float(item[0].width_um),
        ),
    )
    m3, tail, vnb1, psrc_lower = m3_state
    m1 = _matching_input_candidate(
        input_candidates,
        tail_v=float(tail),
        psrc_lower_v=float(psrc_lower),
        voltage_tolerance_v=voltage_tolerance_v,
    )

    compatible_upper = [
        item
        for item in upper_candidates
        if item.vdsat_v is not None
        and psrc <= vdd_v - float(item.vdsat_v) + voltage_tolerance_v
    ]
    if not compatible_upper:
        raise OrderedPropagationError(
            "internal witness error: selected final state has no compatible M4/M5 state"
        )
    upper = max(
        compatible_upper,
        key=lambda item: (
            (vdd_v - psrc) - float(item.vdsat_v or 0.0),
            -abs(float(item.predicted_current_a) - 1.5 * i3_a),
            -float(item.width_um),
        ),
    )
    vpb1 = vdd_v - float(upper.vgs_v)
    vout = 0.5 * (vout_lo + vout_hi)

    margins = {
        "m1_vdsat_margin_v": psrc - float(tail) - float(m1.vdsat_v or 0.0),
        "m3_vdsat_margin_v": float(tail) - vss_v - float(m3.vdsat_v or 0.0),
        "m4_vdsat_margin_v": vdd_v - psrc - float(upper.vdsat_v or 0.0),
        "m6_vdsat_margin_v": psrc - x - float(m6.vdsat_v or 0.0),
        "m8_vdsat_margin_v": x - nsink - float(m8.vdsat_v or 0.0),
        "m10_vdsat_margin_v": nsink - vss_v - float(m10.vdsat_v or 0.0),
        "m7_output_margin_v": psrc - vout - float(m6.vdsat_v or 0.0),
        "m9_output_margin_v": vout - nsink - float(m8.vdsat_v or 0.0),
    }

    return {
        "point_index": int(point_index),
        "status": "PASS",
        "source": "ordered_dc_propagation_native_witness",
        "w_m1_um": float(w1_um),
        "i_m3_a": float(i3_a),
        "nodes": {
            "vdd_v": float(vdd_v),
            "vss_v": float(vss_v),
            "vip_v": float(vin_v),
            "vin_v": float(vin_v),
            "tail_v": float(tail),
            "psrc_left_v": psrc,
            "psrc_right_v": psrc,
            "x_v": x,
            "nsink_left_v": nsink,
            "nsink_right_v": nsink,
            "vnb1_node_v": float(vnb1),
            "vpb1_node_v": float(vpb1),
            "vnb2_node_v": vnb2,
            "vpb2_node_v": vpb2,
            "vout_v": vout,
            "vout_min_v": vout_lo,
            "vout_max_v": vout_hi,
        },
        "widths_um": {
            "M1": float(m1.width_um), "M2": float(m1.width_um),
            "M3": float(m3.width_um),
            "M4": float(upper.width_um), "M5": float(upper.width_um),
            "M6": float(m6.width_um), "M7": float(m6.width_um),
            "M8": float(m8.width_um), "M9": float(m8.width_um),
            "M10": float(m10.width_um), "M11": float(m10.width_um),
        },
        "nf": {
            "M1": int(m1.nf), "M2": int(m1.nf),
            "M3": int(m3.nf),
            "M4": int(upper.nf), "M5": int(upper.nf),
            "M6": int(m6.nf), "M7": int(m6.nf),
            "M8": int(m8.nf), "M9": int(m8.nf),
            "M10": int(m10.nf), "M11": int(m10.nf),
        },
        "biases_v": {
            "vnb1_v": float(vnb1),
            "vpb1_v": float(vpb1),
            "vnb2_v": vnb2,
            "vpb2_v": vpb2,
        },
        "currents_a": {
            "M1": 0.5 * float(i3_a), "M2": 0.5 * float(i3_a),
            "M3": float(i3_a),
            "M4": 1.5 * float(i3_a), "M5": 1.5 * float(i3_a),
            "M6": float(i3_a), "M7": float(i3_a),
            "M8": float(i3_a), "M9": float(i3_a),
            "M10": float(i3_a), "M11": float(i3_a),
        },
        "device_realizations": {
            "M1_M2": _realization_payload(m1),
            "M3": _realization_payload(m3),
            "M4_M5": _realization_payload(upper),
            "M6_M7": _realization_payload(m6),
            "M8_M9": _realization_payload(m8),
            "M10_M11": _realization_payload(m10),
        },
        "saturation_margins_v": margins,
        "minimum_saturation_margin_v": min(margins.values()),
    }


def evaluate_point(
    *,
    point_index: int,
    w1_um: float,
    i3_a: float,
    model: Mapping[str, Any],
    provider: InverseFeasibleDatasetProvider,
    max_candidates: int,
) -> dict[str, Any]:
    operating = _numeric_operating_conditions(model)
    vdd = operating["vdd_v"]
    vss = operating["vss_v"]
    vin = operating["vin_cm_v"]
    voltage_tol = _technology_tolerances(model)["voltage_tolerance_v"]
    record = _empty_record(point_index, w1_um, i3_a, operating)

    input_raw = _query_scaled_fixed_width(
        provider,
        model,
        _device_request(
            model,
            "M1",
            target_current_a=0.5 * i3_a,
            fixed_width_um=w1_um,
        ),
        limit=max_candidates,
    )
    input_candidates: list[tuple[DeviceRealization, float, float]] = []
    for item in input_raw:
        if item.vdsat_v is None:
            continue
        tail_from_vgs = vin - item.vgs_v
        tail_from_vbs = vss + item.vbs_v
        if not math.isclose(
            tail_from_vgs,
            tail_from_vbs,
            rel_tol=0.0,
            abs_tol=voltage_tol,
        ):
            continue
        tail = 0.5 * (tail_from_vgs + tail_from_vbs)
        if tail < vss - voltage_tol or tail > vdd + voltage_tol:
            continue
        input_candidates.append((item, tail, tail + item.vdsat_v))

    record["input_pair_candidate_count"] = len(input_candidates)
    _candidate_summary(record, "input_pair", [item[0] for item in input_candidates])
    if not input_candidates:
        return _fail(record, "lookup_input_pair", "NO_TECHNOLOGY_REALIZATION")

    _set_interval(record, "tail", _interval(item[1] for item in input_candidates))
    record["last_completed_operation"] = "derive_tail"

    m3_by_tail: list[tuple[DeviceRealization, float, float, float]] = []
    for _m1, tail, psrc_lower in input_candidates:
        m3_raw = _query(
            provider,
            model,
            _device_request(
                model,
                "M3",
                target_current_a=i3_a,
                fixed_width_um=None,
                known_vds_v=tail - vss,
                known_vbs_v=0.0,
            ),
            limit=max_candidates,
        )
        for m3 in m3_raw:
            if m3.vdsat_v is None:
                continue
            if tail - vss + voltage_tol < m3.vdsat_v:
                continue
            vnb1 = vss + m3.vgs_v
            m3_by_tail.append((m3, tail, vnb1, psrc_lower))

    record["m3_candidate_count"] = len(m3_by_tail)
    _candidate_summary(record, "m3", [item[0] for item in m3_by_tail])
    if not m3_by_tail:
        return _fail(record, "lookup_m3", "NO_SATURATED_M3_TUPLE")

    _set_interval(record, "vnb1_node", _interval(item[2] for item in m3_by_tail))
    record["last_completed_operation"] = "derive_vnb1"

    upper_raw = _query(
        provider,
        model,
        _device_request(
            model,
            "M4",
            target_current_a=1.5 * i3_a,
            fixed_width_um=None,
            known_vbs_v=0.0,
        ),
        limit=max_candidates,
    )
    upper_candidates = [item for item in upper_raw if item.vdsat_v is not None]
    record["upper_pair_candidate_count"] = len(upper_candidates)
    _candidate_summary(record, "upper_pair", upper_candidates)
    if not upper_candidates:
        return _fail(record, "lookup_upper_current_pair", "NO_TECHNOLOGY_REALIZATION")

    _set_interval(
        record,
        "vpb1_node",
        _interval(vdd - item.vgs_v for item in upper_candidates),
    )
    record["last_completed_operation"] = "derive_vpb1"

    psrc_lower_values = [item[3] for item in m3_by_tail]
    psrc_upper_values = [
        vdd - item.vdsat_v for item in upper_candidates if item.vdsat_v is not None
    ]
    psrc_initial = Interval(min(psrc_lower_values), max(psrc_upper_values))
    _set_interval(record, "psrc_left", psrc_initial)
    _set_interval(record, "psrc_right", psrc_initial)
    if not psrc_initial.valid(voltage_tol):
        return _fail(record, "psrc_shared_upper", "EMPTY_PSRC_INTERVAL")

    lower_raw = _query(
        provider,
        model,
        _device_request(
            model,
            "M10",
            target_current_a=i3_a,
            fixed_width_um=None,
            known_vbs_v=0.0,
        ),
        limit=max_candidates,
    )
    lower_candidates = [item for item in lower_raw if item.vdsat_v is not None]
    record["lower_sink_candidate_count"] = len(lower_candidates)
    _candidate_summary(record, "lower_sink", lower_candidates)
    if not lower_candidates:
        return _fail(record, "lookup_lower_sink_pair", "NO_TECHNOLOGY_REALIZATION")

    _set_interval(record, "x", _interval(vss + item.vgs_v for item in lower_candidates))
    nsink_lower_interval = _interval(vss + item.vdsat_v for item in lower_candidates)
    _set_interval(record, "nsink_left", nsink_lower_interval)
    _set_interval(record, "nsink_right", nsink_lower_interval)
    record["last_completed_operation"] = "nsink_right_lower"

    lower_stack_states: list[
        tuple[DeviceRealization, DeviceRealization, float, float, float]
    ] = []
    for m10 in lower_candidates:
        x = vss + m10.vgs_v
        nsink_min = vss + float(m10.vdsat_v)
        m8_raw = _query(
            provider,
            model,
            _device_request(
                model,
                "M8",
                target_current_a=i3_a,
                fixed_width_um=m10.width_um,
            ),
            limit=max_candidates,
        )
        for m8 in m8_raw:
            if m8.vdsat_v is None:
                continue
            nsink = vss + m8.vbs_v
            if nsink + voltage_tol < nsink_min:
                continue
            if x - nsink + voltage_tol < m8.vdsat_v:
                continue
            vnb2 = nsink + m8.vgs_v
            lower_stack_states.append((m10, m8, x, nsink, vnb2))

    record["nmos_cascode_candidate_count"] = len(lower_stack_states)
    _candidate_summary(record, "nmos_cascode", [item[1] for item in lower_stack_states])
    if not lower_stack_states:
        return _fail(
            record,
            "lookup_nmos_cascode_pair",
            "NO_SHARED_WIDTH_SATURATED_TUPLE",
        )

    _set_interval(record, "x", _interval(item[2] for item in lower_stack_states))
    nsink_interval = _interval(item[3] for item in lower_stack_states)
    _set_interval(record, "nsink_left", nsink_interval)
    _set_interval(record, "nsink_right", nsink_interval)
    _set_interval(record, "vnb2_node", _interval(item[4] for item in lower_stack_states))
    _set_interval(
        record,
        "vout",
        _interval(item[3] + float(item[1].vdsat_v) for item in lower_stack_states),
    )
    record["last_completed_operation"] = "vout_lower_from_m9"

    folded_raw = _query(
        provider,
        model,
        _device_request(
            model,
            "M6",
            target_current_a=i3_a,
            fixed_width_um=None,
        ),
        limit=max_candidates,
    )
    folded_candidates = [item for item in folded_raw if item.vdsat_v is not None]
    record["folded_pmos_candidate_count"] = len(folded_candidates)
    _candidate_summary(record, "folded_pmos", folded_candidates)
    if not folded_candidates:
        return _fail(record, "lookup_folded_pmos_pair", "NO_TECHNOLOGY_REALIZATION")

    # Efficient ordered propagation:
    #
    # M3 and M4/M5 contribute independent lower and upper constraints on
    # psrc. Their candidate sets do not need to be multiplied together.
    # Preserve explicit correlation only between each lower-stack state and
    # each folded-PMOS realization, because x, nsink, and Vout interact there.

    psrc_required_min = min(
        item[3] for item in m3_by_tail
    )
    psrc_required_max = max(
        vdd - float(item.vdsat_v)
        for item in upper_candidates
        if item.vdsat_v is not None
    )

    if psrc_required_min > psrc_required_max + voltage_tol:
        return _fail(
            record,
            "psrc_shared_upper",
            "EMPTY_PSRC_INTERVAL",
        )

    feasible_folded: list[
        tuple[DeviceRealization, float, float, float]
    ] = []

    for m6 in folded_candidates:
        if m6.vdsat_v is None:
            continue

        psrc = vdd - float(m6.vbs_v)
        vpb2 = psrc - float(m6.vgs_v)
        vout_upper = psrc - float(m6.vdsat_v)

        if psrc + voltage_tol < psrc_required_min:
            continue
        if psrc - voltage_tol > psrc_required_max:
            continue

        feasible_folded.append(
            (m6, psrc, vpb2, vout_upper)
        )

    if not feasible_folded:
        return _fail(
            record,
            "lookup_folded_pmos_pair",
            "NO_FOLDED_PMOS_WITHIN_PSRC_INTERVAL",
        )

    # These are the only correlated pairs that must be explicitly retained.
    final_states: list[dict[str, Any]] = []

    for m10, m8, x, nsink, vnb2 in lower_stack_states:
        vout_lower = nsink + float(m8.vdsat_v)

        for m6, psrc, vpb2, vout_upper in feasible_folded:
            # M6 saturation:
            #     psrc - x >= VDSAT6
            if psrc - x + voltage_tol < float(m6.vdsat_v):
                continue

            # M7 and M9 output windows must overlap.
            if vout_lower > vout_upper + voltage_tol:
                continue

            final_states.append(
                {
                    "x_v": x,
                    "nsink_v": nsink,
                    "vnb2_node_v": vnb2,
                    "psrc_v": psrc,
                    "vpb2_node_v": vpb2,
                    "vout_min_v": vout_lower,
                    "vout_max_v": vout_upper,
                    "w_m6_um": float(m6.width_um),
                    "w_m8_um": float(m8.width_um),
                    # Keep the exact accepted realizations locally so a native
                    # witness can be emitted without a second technology search.
                    "m10": m10,
                    "m8": m8,
                    "m6": m6,
                }
            )

    if not final_states:
        return _fail(
            record,
            "vout_upper_from_m7",
            "NO_NONEMPTY_FINAL_VOLTAGE_REGION",
        )

    # M1/M3 values are already correlated in m3_by_tail.
    _set_interval(
        record,
        "tail",
        _interval(
            item[1] for item in m3_by_tail
        ),
    )
    _set_interval(
        record,
        "vnb1_node",
        _interval(
            item[2] for item in m3_by_tail
        ),
    )

    # M4/M5 bias values come directly from valid upper-pair realizations.
    _set_interval(
        record,
        "vpb1_node",
        _interval(
            vdd - float(item.vgs_v)
            for item in upper_candidates
        ),
    )

    psrc_interval = _interval(
        item["psrc_v"] for item in final_states
    )
    _set_interval(record, "psrc_left", psrc_interval)
    _set_interval(record, "psrc_right", psrc_interval)

    _set_interval(
        record,
        "x",
        _interval(
            item["x_v"] for item in final_states
        ),
    )

    nsink_interval = _interval(
        item["nsink_v"] for item in final_states
    )
    _set_interval(record, "nsink_left", nsink_interval)
    _set_interval(record, "nsink_right", nsink_interval)

    _set_interval(
        record,
        "vnb2_node",
        _interval(
            item["vnb2_node_v"]
            for item in final_states
        ),
    )
    _set_interval(
        record,
        "vpb2_node",
        _interval(
            item["vpb2_node_v"]
            for item in final_states
        ),
    )
    _set_interval(
        record,
        "vout",
        Interval(
            min(
                item["vout_min_v"]
                for item in final_states
            ),
            max(
                item["vout_max_v"]
                for item in final_states
            ),
        ),
    )

    for width_name, values in {
        "w_m3_um": (
            item[0].width_um
            for item in m3_by_tail
        ),
        "w_m4_um": (
            item.width_um
            for item in upper_candidates
        ),
        "w_m6_um": (
            item["w_m6_um"]
            for item in final_states
        ),
        "w_m8_um": (
            item["w_m8_um"]
            for item in final_states
        ),
    }.items():
        interval = _interval(values)
        if interval is not None:
            record[f"{width_name}_min"] = interval.minimum
            record[f"{width_name}_max"] = interval.maximum

    record["_native_witness"] = _select_native_witness(
        point_index=point_index,
        w1_um=w1_um,
        i3_a=i3_a,
        vdd_v=vdd,
        vss_v=vss,
        vin_v=vin,
        voltage_tolerance_v=voltage_tol,
        input_candidates=input_candidates,
        m3_by_tail=m3_by_tail,
        upper_candidates=upper_candidates,
        final_states=final_states,
    )

    record["status"] = "PASS"
    record["failure_operation"] = None
    record["failure_reason"] = None
    record["last_completed_operation"] = "vout_upper_from_m7"
    record["final_feasible_tuple_count"] = len(final_states)
    return record


def build_design_space(
    *,
    compiled_model_path: Path,
    independent_regions_path: Path,
    technology_csv_path: Path,
    w1_samples: int | None,
    w1_min_um: float | None,
    w1_max_um: float | None,
    max_candidates: int,
) -> dict[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    independent = json.loads(independent_regions_path.read_text(encoding="utf-8"))

    domains = independent["domains"]
    w1_domain = domains["w_m1_um"]
    i3_domain = domains["i_m3_a"]

    count = int(w1_samples or w1_domain.get("sample_count") or 25)
    minimum = max(
        float(w1_domain["technology_minimum"]),
        float(w1_min_um) if w1_min_um is not None else float(w1_domain["technology_minimum"]),
    )
    maximum = min(
        float(w1_domain["technology_maximum"]),
        float(w1_max_um) if w1_max_um is not None else float(w1_domain["technology_maximum"]),
    )
    w1_values = _linspace(minimum, maximum, count)
    i3_values = [float(value) for value in i3_domain["candidate_values"]]

    provider = InverseFeasibleDatasetProvider(
        technology_csv_path,
        saturation_margin_v=float(
            model["project_inputs"]["design_rules"]
            .get("technology_intersection", {})
            .get("saturation_margin_v", 0.0)
        ),
    )

    records: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    for point_index, (w1, i3) in enumerate(itertools.product(w1_values, i3_values)):
        record = evaluate_point(
            point_index=point_index,
            w1_um=w1,
            i3_a=i3,
            model=model,
            provider=provider,
            max_candidates=max_candidates,
        )
        witness = record.pop("_native_witness", None)
        records.append(record)
        if witness is not None:
            witnesses.append(witness)

    status_counts = Counter(str(item["status"]) for item in records)
    failure_counts = Counter(
        str(item["failure_operation"])
        for item in records
        if item["status"] == "FAIL"
    )

    return {
        "artifact": "openams.ordered_dc_design_space",
        "schema_version": 1,
        "status": "PASS",
        "algorithm": "ordered_technology_conditioned_dc_propagation",
        "circuit_name": model["circuit_name"],
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "technology_source": str(technology_csv_path.resolve()),
        "w1_values": w1_values,
        "i3_values": i3_values,
        "independent_point_count": len(records),
        "pass_count": status_counts.get("PASS", 0),
        "fail_count": status_counts.get("FAIL", 0),
        "failure_operation_counts": dict(sorted(failure_counts.items())),
        "technology_provider_query_count": provider.query_count,
        "max_candidates_per_lookup": int(max_candidates),
        "witness_count": len(witnesses),
        "records": records,
        "_native_witnesses": witnesses,
    }


def write_outputs(
    artifact: Mapping[str, Any],
    json_path: Path,
    csv_path: Path,
    witness_jsonl_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    witness_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    public_artifact = {
        key: value
        for key, value in artifact.items()
        if not str(key).startswith("_")
    }
    json_path.write_text(
        json.dumps(public_artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    witnesses = list(artifact.get("_native_witnesses", []) or [])
    with witness_jsonl_path.open("w", encoding="utf-8") as stream:
        for witness in witnesses:
            stream.write(json.dumps(witness, sort_keys=True, default=str) + "\n")

    records = list(artifact["records"])
    fields = sorted(
        {key for record in records for key in record},
        key=lambda key: (
            key not in {
                "point_index", "w_m1_um", "i_m3_a", "status",
                "failure_operation", "failure_reason", "last_completed_operation",
            },
            key,
        ),
    )
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled-model", type=Path, required=True)
    parser.add_argument("--independent-regions", type=Path, required=True)
    parser.add_argument("--technology-csv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument(
        "--output-witness-jsonl",
        type=Path,
        help=(
            "Native PASS witnesses. Defaults beside --output-json as "
            "<stem>_witnesses.jsonl."
        ),
    )
    parser.add_argument("--w1-samples", type=int)
    parser.add_argument("--w1-min-um", type=float)
    parser.add_argument("--w1-max-um", type=float)
    parser.add_argument("--max-candidates", type=int, default=100000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = build_design_space(
        compiled_model_path=args.compiled_model,
        independent_regions_path=args.independent_regions,
        technology_csv_path=args.technology_csv,
        w1_samples=args.w1_samples,
        w1_min_um=args.w1_min_um,
        w1_max_um=args.w1_max_um,
        max_candidates=args.max_candidates,
    )
    witness_path = args.output_witness_jsonl or args.output_json.with_name(
        f"{args.output_json.stem}_witnesses.jsonl"
    )
    write_outputs(artifact, args.output_json, args.output_csv, witness_path)
    print("===== OPENAMS ORDERED DC DESIGN SPACE =====")
    print(f"algorithm:          {artifact['algorithm']}")
    print(f"independent points: {artifact['independent_point_count']}")
    print(f"PASS:               {artifact['pass_count']}")
    print(f"FAIL:               {artifact['fail_count']}")
    print(f"native witnesses:   {artifact['witness_count']}")
    print(f"JSON:               {args.output_json}")
    print(f"CSV:                {args.output_csv}")
    print(f"witness JSONL:      {witness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
