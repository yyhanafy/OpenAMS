"""Assignment-synthesis Step 5: indexed complete DC assignment construction.

This revision fixes two defects in the first implementation:

1. It does not perform a brute-force input_candidates × output_candidates join.
2. It enforces the nonlinear second-stage width relation analytically and uses
   linear interpolation of M6 current density between neighboring technology
   rows at fixed VSD, rather than requiring an accidental exact match on a
   sparse characterization grid.

For a fixed input candidate and M7 technology row:

    d7 = I7 / W7
    required d6 = d7 * W5 / (2 * W4)

because current equality and

    W6 / W4 = 2 * W7 / W5

imply that relationship between the M6/M7 current densities.

M6 VSG is then interpolated at the required density for the selected VSD.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class CompleteAssignmentError(ValueError):
    pass


@dataclass(frozen=True)
class TechRow:
    index: int
    polarity: str
    model: str
    length_um: float
    width_um: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    id_a: float
    saturated: bool

    @property
    def density_a_per_um(self) -> float:
        return self.id_a / self.width_um


def _num(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompleteAssignmentError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise CompleteAssignmentError(f"{name} must be finite: {value!r}")
    return result


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    raise CompleteAssignmentError(f"missing fields {names!r}")


def load_rows(path: Path) -> tuple[TechRow, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        result = tuple(
            TechRow(
                index=index,
                polarity=str(row["polarity"]).lower(),
                model=str(row["model"]),
                length_um=_num(row["length_um"], "length_um"),
                width_um=_num(row["width_um"], "width_um"),
                vgs_v=_num(_first(row, "vgs_v", "vgs_abs_v"), "vgs"),
                vds_v=_num(_first(row, "vds_v", "vds_abs_v"), "vds"),
                vbs_v=_num(_first(row, "vbs_v", "vbs_abs_v"), "vbs"),
                id_a=_num(_first(row, "id_abs_a", "id_a", "id"), "id"),
                saturated=_truth(row.get("saturated", True)),
            )
            for index, row in enumerate(reader)
        )
    if not result:
        raise CompleteAssignmentError(f"empty technology table: {path}")
    return result


def _device_map(model: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for item in model["topology"]["devices"]:
        raw = str(item["name"])
        name = raw[1:] if raw.upper().startswith("X") else raw
        result[name.upper()] = item
    return result


def _polarity(model_name: str) -> str:
    token = model_name.lower()
    if "pfet" in token or "pmos" in token:
        return "pmos"
    if "nfet" in token or "nmos" in token:
        return "nmos"
    raise CompleteAssignmentError(f"cannot infer polarity from {model_name!r}")


def _filtered_rows(
    rows: Sequence[TechRow],
    device: Mapping[str, Any],
    *,
    length_um: float,
    body_limit_v: float,
) -> tuple[TechRow, ...]:
    model_name = str(device["model"])
    polarity = _polarity(model_name)
    return tuple(
        row for row in rows
        if row.model == model_name
        and row.polarity == polarity
        and math.isclose(row.length_um, length_um, rel_tol=0.0, abs_tol=1e-12)
        and row.saturated
        and abs(row.vbs_v) <= body_limit_v + 1e-15
        and row.id_a > 0.0
        and row.width_um > 0.0
    )


def _technology_path(model: Mapping[str, Any]) -> Path:
    path = model.get("technology", {}).get("source_path")
    if not path:
        raise CompleteAssignmentError("compiled model has no technology source_path")
    return Path(path).resolve()


def _width_policy(model: Mapping[str, Any]) -> dict[str, Any]:
    policy = (
        model["project_inputs"]["design_intent"]["synthesis_parameterization"]
        ["dependent_width_realization"]
    )
    return {
        "total_min_um": _num(policy["total_width_min_um"], "total_width_min_um"),
        "total_max_um": _num(policy["total_width_max_um"], "total_width_max_um"),
        "finger_min_um": _num(policy["finger_width_min_um"], "finger_width_min_um"),
        "finger_max_um": _num(policy["finger_width_max_um"], "finger_width_max_um"),
        "nf_min": int(policy["nf_min"]),
        "nf_max": int(policy["nf_max"]),
    }


def _minimum_nf(width: float, policy: Mapping[str, Any]) -> int | None:
    if not policy["total_min_um"] <= width <= policy["total_max_um"]:
        return None
    for nf in range(policy["nf_min"], policy["nf_max"] + 1):
        finger = width / nf
        if policy["finger_min_um"] <= finger <= policy["finger_max_um"]:
            return nf
    return None


def _current_close(
    actual: float,
    target: float,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    tolerance = max(
        absolute_tolerance,
        relative_tolerance * max(abs(actual), abs(target), 1e-30),
    )
    return abs(actual - target) <= tolerance


def _build_input_candidates(
    model: Mapping[str, Any],
    independent: Mapping[str, Any],
    rows: Sequence[TechRow],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    operating = rules["operating_conditions"]
    intersection = rules["technology_intersection"]
    all_mos = rules["device_constraints"]["all_mos"]
    policy = _width_policy(model)

    vdd = _num(operating["vdd_v"], "vdd_v")
    vss = _num(operating["vss_v"], "vss_v")
    vin = _num(operating["vin_cm_v"], "vin_cm_v")
    length = _num(all_mos["length_um"], "length_um")
    body_limit = _num(all_mos["body_voltage_abs_max_v"], "body limit")
    node_tol = _num(intersection["node_voltage_tolerance_v"], "node tolerance")
    diode_tol = _num(intersection["diode_voltage_tolerance_v"], "diode tolerance")
    abs_i_tol = _num(intersection["current_absolute_tolerance_a"], "current abs tolerance")
    rel_i_tol = _num(intersection["current_relative_tolerance"], "current rel tolerance")
    max_candidates = int(intersection["max_assignments"])

    current_values = [
        _num(value, "i_m5 candidate")
        for value in independent["domains"]["i_m5_a"]["candidate_values"]
    ]
    w1_domain = independent["domains"]["w_m1_um"]
    w1_min = _num(w1_domain["technology_minimum"], "w1 minimum")
    w1_max = _num(w1_domain["technology_maximum"], "w1 maximum")

    m1_rows = _filtered_rows(rows, devices["M1"], length_um=length, body_limit_v=body_limit)
    m3_rows = _filtered_rows(rows, devices["M3"], length_um=length, body_limit_v=body_limit)
    m5_rows = _filtered_rows(rows, devices["M5"], length_um=length, body_limit_v=body_limit)
    diode_m3 = tuple(row for row in m3_rows if abs(row.vgs_v - row.vds_v) <= diode_tol)

    candidates: dict[tuple[Any, ...], dict[str, Any]] = {}
    rejection = {
        "m1_width_illegal": 0,
        "m5_voltage_mismatch": 0,
        "m5_width_illegal": 0,
        "m3_n1_mismatch": 0,
        "m3_width_illegal": 0,
        "m4_current_mismatch": 0,
        "candidate_cap_reached": 0,
    }

    for i5 in current_values:
        i1 = 0.5 * i5
        for row1 in m1_rows:
            w1 = i1 / row1.density_a_per_um
            nf1 = _minimum_nf(w1, policy)
            if not (w1_min <= w1 <= w1_max) or nf1 is None:
                rejection["m1_width_illegal"] += 1
                continue

            vtail = vin - row1.vgs_v
            if not (vss <= vtail <= vin):
                continue
            n1_from_m1 = vtail + row1.vds_v
            if not (vss <= n1_from_m1 <= vdd):
                continue

            matching_m5 = [
                row for row in m5_rows
                if abs((vss + row.vds_v) - vtail) <= node_tol
            ]
            if not matching_m5:
                rejection["m5_voltage_mismatch"] += 1
                continue

            matching_m3 = [
                row for row in diode_m3
                if abs((vdd - row.vgs_v) - n1_from_m1) <= node_tol
            ]
            if not matching_m3:
                rejection["m3_n1_mismatch"] += 1
                continue

            for row5 in matching_m5:
                w5 = i5 / row5.density_a_per_um
                nf5 = _minimum_nf(w5, policy)
                if nf5 is None:
                    rejection["m5_width_illegal"] += 1
                    continue
                vbias = vss + row5.vgs_v

                for row3 in matching_m3:
                    w3 = i1 / row3.density_a_per_um
                    nf3 = _minimum_nf(w3, policy)
                    if nf3 is None:
                        rejection["m3_width_illegal"] += 1
                        continue

                    for row4 in m3_rows:
                        if abs(row4.vgs_v - row3.vgs_v) > node_tol:
                            continue
                        i4 = row4.density_a_per_um * w3
                        if not _current_close(
                            i4,
                            i1,
                            absolute_tolerance=abs_i_tol,
                            relative_tolerance=rel_i_tol,
                        ):
                            rejection["m4_current_mismatch"] += 1
                            continue
                        n2 = vdd - row4.vds_v
                        if not (vss <= n2 <= vdd):
                            continue

                        key = (
                            round(i5, 15),
                            round(w1, 12),
                            round(w3, 12),
                            round(w5, 12),
                            round(vtail, 9),
                            round(n1_from_m1, 9),
                            round(n2, 9),
                            round(vbias, 9),
                            row1.index,
                            row3.index,
                            row4.index,
                            row5.index,
                        )
                        candidates[key] = {
                            "i_m5_a": i5,
                            "i_m1_a": i1,
                            "i_m2_a": i1,
                            "i_m3_a": i1,
                            "i_m4_a": i4,
                            "w_m1_um": w1,
                            "w_m2_um": w1,
                            "w_m3_um": w3,
                            "w_m4_um": w3,
                            "w_m5_um": w5,
                            "nf_m1": nf1,
                            "nf_m2": nf1,
                            "nf_m3": nf3,
                            "nf_m4": nf3,
                            "nf_m5": nf5,
                            "w_finger_m1_um": w1 / nf1,
                            "w_finger_m2_um": w1 / nf1,
                            "w_finger_m3_um": w3 / nf3,
                            "w_finger_m4_um": w3 / nf3,
                            "w_finger_m5_um": w5 / nf5,
                            "vtail_v": vtail,
                            "n1_v": n1_from_m1,
                            "n2_v": n2,
                            "vbias_v": vbias,
                            "m1_technology_row_index": row1.index,
                            "m2_technology_row_index": row1.index,
                            "m3_technology_row_index": row3.index,
                            "m4_technology_row_index": row4.index,
                            "m5_technology_row_index": row5.index,
                        }
                        if len(candidates) >= max_candidates:
                            rejection["candidate_cap_reached"] += 1
                            return list(candidates.values()), rejection

    return list(candidates.values()), rejection


def _group_by_vds(rows: Sequence[TechRow], digits: int = 9) -> dict[float, list[TechRow]]:
    groups: dict[float, list[TechRow]] = {}
    for row in rows:
        groups.setdefault(round(row.vds_v, digits), []).append(row)
    for values in groups.values():
        values.sort(key=lambda row: row.density_a_per_um)
    return groups


def _interpolate_m6(
    rows: Sequence[TechRow],
    target_density: float,
) -> dict[str, Any] | None:
    ordered = sorted(rows, key=lambda row: row.density_a_per_um)
    for row in ordered:
        if math.isclose(
            row.density_a_per_um,
            target_density,
            rel_tol=1e-12,
            abs_tol=1e-18,
        ):
            return {
                "density_a_per_um": target_density,
                "vgs_v": row.vgs_v,
                "lower_row_index": row.index,
                "upper_row_index": row.index,
                "interpolation_fraction": 0.0,
            }

    for lower, upper in zip(ordered, ordered[1:]):
        d0 = lower.density_a_per_um
        d1 = upper.density_a_per_um
        if d0 <= target_density <= d1 and d1 > d0:
            fraction = (target_density - d0) / (d1 - d0)
            vgs = lower.vgs_v + fraction * (upper.vgs_v - lower.vgs_v)
            return {
                "density_a_per_um": target_density,
                "vgs_v": vgs,
                "lower_row_index": lower.index,
                "upper_row_index": upper.index,
                "interpolation_fraction": fraction,
            }
    return None


def _construct_complete(
    model: Mapping[str, Any],
    input_candidates: Sequence[Mapping[str, Any]],
    rows: Sequence[TechRow],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    operating = rules["operating_conditions"]
    intersection = rules["technology_intersection"]
    all_mos = rules["device_constraints"]["all_mos"]
    policy = _width_policy(model)

    vdd = _num(operating["vdd_v"], "vdd_v")
    vss = _num(operating["vss_v"], "vss_v")
    length = _num(all_mos["length_um"], "length_um")
    body_limit = _num(all_mos["body_voltage_abs_max_v"], "body limit")
    node_tol = _num(intersection["node_voltage_tolerance_v"], "node tolerance")
    max_assignments = int(intersection["max_assignments"])

    m6_rows = _filtered_rows(rows, devices["M6"], length_um=length, body_limit_v=body_limit)
    m7_rows = _filtered_rows(rows, devices["M7"], length_um=length, body_limit_v=body_limit)
    m6_by_vds = _group_by_vds(m6_rows)

    complete: list[dict[str, Any]] = []
    rejection = {
        "m7_vbias_mismatch": 0,
        "m7_vout_outside_domain": 0,
        "m6_vds_grid_missing": 0,
        "m6_density_not_bracketed": 0,
        "m6_n2_mismatch": 0,
        "empty_common_current_interval": 0,
        "illegal_output_width": 0,
        "assignment_cap_reached": 0,
    }

    vout_domain = (
        model["project_inputs"]["design_intent"]["synthesis_parameterization"]
        ["independent_variables"]["vout_v"]
    )
    spec_output = (
        model["project_inputs"]["specifications"]["dc_validity"]["output_voltage"]
    )
    vout_min = max(_num(vout_domain["minimum"], "vout minimum"), _num(spec_output["min"], "spec minimum"))
    vout_max = min(_num(vout_domain["maximum"], "vout maximum"), _num(spec_output["max"], "spec maximum"))

    for left in input_candidates:
        for row7 in m7_rows:
            vbias = vss + row7.vgs_v
            if abs(vbias - left["vbias_v"]) > node_tol:
                rejection["m7_vbias_mismatch"] += 1
                continue

            vout = vss + row7.vds_v
            if not (vout_min <= vout <= vout_max):
                rejection["m7_vout_outside_domain"] += 1
                continue

            required_vds6 = vdd - vout
            key = round(required_vds6, 9)
            candidate_rows6 = m6_by_vds.get(key)
            if not candidate_rows6:
                rejection["m6_vds_grid_missing"] += 1
                continue

            d7 = row7.density_a_per_um
            target_d6 = d7 * left["w_m5_um"] / (2.0 * left["w_m4_um"])
            interpolated = _interpolate_m6(candidate_rows6, target_d6)
            if interpolated is None:
                rejection["m6_density_not_bracketed"] += 1
                continue

            n2 = vdd - interpolated["vgs_v"]
            if abs(n2 - left["n2_v"]) > node_tol:
                rejection["m6_n2_mismatch"] += 1
                continue

            d6 = target_d6
            current_min = max(
                d6 * policy["total_min_um"],
                d7 * policy["total_min_um"],
            )
            current_max = min(
                d6 * policy["total_max_um"],
                d7 * policy["total_max_um"],
            )
            if current_min > current_max:
                rejection["empty_common_current_interval"] += 1
                continue

            for current in (current_min, current_max):
                w6 = current / d6
                w7 = current / d7
                nf6 = _minimum_nf(w6, policy)
                nf7 = _minimum_nf(w7, policy)
                if nf6 is None or nf7 is None:
                    rejection["illegal_output_width"] += 1
                    continue

                ratio_left = w6 / left["w_m4_um"]
                ratio_right = 2.0 * w7 / left["w_m5_um"]
                ratio_error = abs(ratio_left - ratio_right) / max(
                    abs(ratio_left), abs(ratio_right), 1e-30
                )

                row = {
                    "assignment_id": f"assignment_{len(complete):06d}",
                    **dict(left),
                    "vout_v": vout,
                    "i_m6_a": current,
                    "i_m7_a": current,
                    "w_m6_um": w6,
                    "w_m7_um": w7,
                    "nf_m6": nf6,
                    "nf_m7": nf7,
                    "w_finger_m6_um": w6 / nf6,
                    "w_finger_m7_um": w7 / nf7,
                    "m6_density_a_per_um": d6,
                    "m7_density_a_per_um": d7,
                    "m6_vgs_v": interpolated["vgs_v"],
                    "m6_vds_v": required_vds6,
                    "m7_vgs_v": row7.vgs_v,
                    "m7_vds_v": row7.vds_v,
                    "m6_lower_technology_row_index": interpolated["lower_row_index"],
                    "m6_upper_technology_row_index": interpolated["upper_row_index"],
                    "m6_interpolation_fraction": interpolated["interpolation_fraction"],
                    "m7_technology_row_index": row7.index,
                    "second_stage_ratio_left": ratio_left,
                    "second_stage_ratio_right": ratio_right,
                    "second_stage_ratio_relative_error": ratio_error,
                    "assignment_semantics": "complete_correlated_circuit_assignment",
                    "route": "direct_simulation",
                }
                complete.append(row)
                if len(complete) >= max_assignments:
                    rejection["assignment_cap_reached"] += 1
                    return complete, rejection

    return complete, rejection


def build_complete_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    dependent_regions_path: Path,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    independent = json.loads(independent_regions_path.read_text(encoding="utf-8"))
    dependent = json.loads(dependent_regions_path.read_text(encoding="utf-8"))
    rows = load_rows(_technology_path(model))

    input_candidates, input_rejection = _build_input_candidates(
        model, independent, rows
    )
    complete, join_rejection = _construct_complete(
        model, input_candidates, rows
    )

    output_candidate_count = len(
        next(
            group for group in dependent["groups"]
            if group["group_id"] == "output_stage"
        )["correlated_candidates"]
    )

    return {
        "artifact": "openams.complete_dc_assignments",
        "schema_version": 2,
        "status": "PASS" if complete else "FAIL",
        "circuit_name": model["circuit_name"],
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "dependent_regions": str(dependent_regions_path.resolve()),
        "technology_source": str(_technology_path(model)),
        "algorithm": "indexed_density_interpolation",
        "input_bias_candidate_count": len(input_candidates),
        "step4_output_candidate_count": output_candidate_count,
        "complete_assignment_count": len(complete),
        "fixed_assignment_count": len(complete),
        "ranged_assignment_count": 0,
        "recommended_route": "direct_simulation" if complete else "blocked",
        "input_rejection_counts": input_rejection,
        "join_rejection_counts": join_rejection,
        "assignments": complete,
        "next_stage": "ngspice_dc_confirmation" if complete else "diagnose_empty_intersection",
    }


def write_complete_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    dependent_regions_path: Path,
    output_json: Path,
    output_csv: Path,
) -> Mapping[str, Any]:
    artifact = build_complete_assignments(
        compiled_model_path,
        independent_regions_path,
        dependent_regions_path,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    assignments = artifact["assignments"]
    if assignments:
        fields = sorted(
            {key for row in assignments for key in row},
            key=lambda name: (name != "assignment_id", name),
        )
        with output_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(assignments)
    else:
        output_csv.write_text("", encoding="utf-8")
    return artifact
