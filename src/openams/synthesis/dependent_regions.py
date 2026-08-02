"""Assignment-synthesis Step 4: derive physically bounded correlated regions.

This revision keeps the original group-ordered architecture but strengthens the
two-stage adapters in two ways:

1. Every derived node voltage is clipped to valid circuit/supply bounds.
2. The output-stage adapter emits correlated candidate tuples
   ``(n2, vbias, vout, i6=i7, w6, w7)`` instead of representing the whole
   output stage only by a loose min/max envelope.

The final nonlinear width relation and complete full-circuit assignment
intersection remain Step 5 responsibilities.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class DependentRegionError(ValueError):
    """Raised when a dependent region cannot be derived."""


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


def _num(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DependentRegionError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise DependentRegionError(f"{name} must be finite: {value!r}")
    return result


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    raise DependentRegionError(f"missing fields {names!r}")


def load_rows(path: Path) -> tuple[TechRow, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = [
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
        ]
    if not rows:
        raise DependentRegionError(f"empty technology table: {path}")
    return tuple(rows)


def _interval(minimum: float, maximum: float) -> dict[str, float]:
    if minimum > maximum:
        raise DependentRegionError(f"empty interval [{minimum}, {maximum}]")
    return {"minimum": minimum, "maximum": maximum}


def _values_interval(values: Iterable[float], name: str) -> dict[str, float]:
    materialized = [float(value) for value in values]
    if not materialized:
        raise DependentRegionError(f"no values for {name}")
    return _interval(min(materialized), max(materialized))


def _intersect(*intervals: Mapping[str, Any]) -> dict[str, float]:
    return _interval(
        max(_num(item["minimum"], "minimum") for item in intervals),
        min(_num(item["maximum"], "maximum") for item in intervals),
    )


def _scale_interval(interval: Mapping[str, Any], scale: float) -> dict[str, float]:
    a = _num(interval["minimum"], "minimum") * scale
    b = _num(interval["maximum"], "maximum") * scale
    return _interval(min(a, b), max(a, b))


def _clip_interval(
    interval: Mapping[str, Any],
    minimum: float,
    maximum: float,
) -> dict[str, float]:
    return _intersect(interval, {"minimum": minimum, "maximum": maximum})


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
    raise DependentRegionError(f"cannot infer polarity from {model_name!r}")


def _technology_path(model: Mapping[str, Any]) -> Path:
    path = model.get("technology", {}).get("source_path")
    if not path:
        raise DependentRegionError("compiled model has no technology source_path")
    return Path(path).resolve()


def _filtered_rows(
    rows: Sequence[TechRow],
    device: Mapping[str, Any],
    *,
    length_um: float,
    body_limit_v: float,
) -> tuple[TechRow, ...]:
    model_name = str(device["model"])
    polarity = _polarity(model_name)
    result = tuple(
        row
        for row in rows
        if row.model == model_name
        and row.polarity == polarity
        and math.isclose(row.length_um, length_um, rel_tol=0.0, abs_tol=1e-12)
        and row.saturated
        and abs(row.vbs_v) <= body_limit_v + 1e-15
        and row.id_a > 0.0
        and row.width_um > 0.0
    )
    if not result:
        raise DependentRegionError(f"no filtered rows for {model_name}")
    return result


def _width_policy(model: Mapping[str, Any]) -> dict[str, float]:
    intent = model["project_inputs"]["design_intent"]
    parameterization = intent["synthesis_parameterization"]
    policy = parameterization.get("dependent_width_realization", {})
    rules = model["project_inputs"]["design_rules"]["device_constraints"]["all_mos"]

    finger_min = _num(
        policy.get("finger_width_min_um", rules["width_min_um"]),
        "finger_width_min_um",
    )
    finger_max = _num(
        policy.get("finger_width_max_um", rules["width_max_um"]),
        "finger_width_max_um",
    )
    nf_min = int(policy.get("nf_min", 1))
    nf_max = int(policy.get("nf_max", 3))
    total_min = _num(
        policy.get("total_width_min_um", finger_min * nf_min),
        "total_width_min_um",
    )
    total_max = _num(
        policy.get("total_width_max_um", finger_max * nf_max),
        "total_width_max_um",
    )
    return {
        "finger_min_um": finger_min,
        "finger_max_um": finger_max,
        "nf_min": nf_min,
        "nf_max": nf_max,
        "total_min_um": total_min,
        "total_max_um": total_max,
    }


def _legal_total_width(width_um: float, policy: Mapping[str, Any]) -> bool:
    if not (policy["total_min_um"] <= width_um <= policy["total_max_um"]):
        return False
    return any(
        policy["finger_min_um"] <= width_um / nf <= policy["finger_max_um"]
        for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1)
    )


def _minimum_nf(width_um: float, policy: Mapping[str, Any]) -> int | None:
    for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1):
        finger = width_um / nf
        if policy["finger_min_um"] <= finger <= policy["finger_max_um"]:
            return nf
    return None


def _required_total_width(row: TechRow, target_current_a: float) -> float:
    return row.width_um * target_current_a / row.id_a


def _row_can_realize_current_interval(
    row: TechRow,
    current: Mapping[str, Any],
    width: Mapping[str, Any],
) -> bool:
    current_min = _num(current["minimum"], "current.minimum")
    current_max = _num(current["maximum"], "current.maximum")
    width_min = _num(width["minimum"], "width.minimum")
    width_max = _num(width["maximum"], "width.maximum")
    scaled_min = row.id_a * width_min / row.width_um
    scaled_max = row.id_a * width_max / row.width_um
    return max(current_min, scaled_min) <= min(current_max, scaled_max)


def _derived_width_interval(
    rows: Sequence[TechRow],
    current: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    widths = []
    evidence = []
    for row in rows:
        for target in (
            _num(current["minimum"], "current.minimum"),
            _num(current["maximum"], "current.maximum"),
        ):
            width = _required_total_width(row, target)
            nf = _minimum_nf(width, policy)
            if nf is not None:
                widths.append(width)
                evidence.append(
                    {
                        "technology_row_index": row.index,
                        "target_current_a": target,
                        "required_total_width_um": width,
                        "nf": nf,
                        "finger_width_um": width / nf,
                        "vgs_v": row.vgs_v,
                        "vds_v": row.vds_v,
                    }
                )
    if not widths:
        raise DependentRegionError("no legal derived width")
    return {
        **_values_interval(widths, "derived width"),
        "width_semantics": "total_effective_width",
        "scaling_model": "linear_current_scaling",
        "evidence_count": len(evidence),
        "evidence": evidence,
    }


def _domain_interval(domain: Mapping[str, Any]) -> dict[str, float]:
    minimum = domain.get("technology_minimum", domain.get("minimum"))
    maximum = domain.get("technology_maximum", domain.get("maximum"))
    if minimum is None or maximum is None:
        minimum = domain.get("declared_effective_minimum")
        maximum = domain.get("declared_effective_maximum")
    return _interval(
        _num(minimum, "domain minimum"),
        _num(maximum, "domain maximum"),
    )


def _candidate_current_interval(domain: Mapping[str, Any]) -> dict[str, float]:
    values = domain.get("candidate_values") or []
    return _values_interval(values, "candidate currents") if values else _domain_interval(domain)


def _input_bias_adapter(
    model: Mapping[str, Any],
    independent: Mapping[str, Any],
    rows: Sequence[TechRow],
) -> dict[str, Any]:
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    operating = rules["operating_conditions"]
    device_rules = rules["device_constraints"]["all_mos"]
    length_um = _num(device_rules["length_um"], "length_um")
    body_limit = _num(device_rules["body_voltage_abs_max_v"], "body limit")
    width_policy = _width_policy(model)

    vdd = _num(operating["vdd_v"], "vdd_v")
    vss = _num(operating["vss_v"], "vss_v")
    vin_cm = _num(operating["vin_cm_v"], "vin_cm_v")

    i5 = _candidate_current_interval(independent["domains"]["i_m5_a"])
    w1 = _domain_interval(independent["domains"]["w_m1_um"])
    i1 = _scale_interval(i5, 0.5)
    i2 = dict(i1)
    i3 = dict(i1)
    i4 = dict(i1)

    m1_rows = _filtered_rows(rows, devices["M1"], length_um=length_um, body_limit_v=body_limit)
    m3_rows = _filtered_rows(rows, devices["M3"], length_um=length_um, body_limit_v=body_limit)
    m5_rows = _filtered_rows(rows, devices["M5"], length_um=length_um, body_limit_v=body_limit)

    feasible_m1 = tuple(
        row for row in m1_rows
        if _row_can_realize_current_interval(row, i1, w1)
    )
    if not feasible_m1:
        raise DependentRegionError("M1 has no feasible technology rows")

    raw_vtail = _values_interval(
        (vin_cm - row.vgs_v for row in feasible_m1),
        "vtail",
    )
    vtail = _clip_interval(raw_vtail, vss, vin_cm)

    feasible_m1 = tuple(
        row for row in feasible_m1
        if vtail["minimum"] <= vin_cm - row.vgs_v <= vtail["maximum"]
    )
    if not feasible_m1:
        raise DependentRegionError("M1 rows disappear after Vtail clipping")

    n1_from_m1 = _clip_interval(
        _values_interval(
            (vin_cm - row.vgs_v + row.vds_v for row in feasible_m1),
            "n1 from M1",
        ),
        vss,
        vdd,
    )

    feasible_m5 = tuple(
        row for row in m5_rows
        if vtail["minimum"] <= vss + row.vds_v <= vtail["maximum"]
    )
    if not feasible_m5:
        raise DependentRegionError("M5 has no rows consistent with clipped Vtail")

    vbias = _clip_interval(
        _values_interval((vss + row.vgs_v for row in feasible_m5), "vbias"),
        vss,
        vdd,
    )
    w5 = _derived_width_interval(feasible_m5, i5, width_policy)

    diode_tolerance = _num(
        rules["technology_intersection"]["diode_voltage_tolerance_v"],
        "diode tolerance",
    )
    feasible_m3 = tuple(
        row for row in m3_rows
        if abs(row.vgs_v - row.vds_v) <= diode_tolerance
        and n1_from_m1["minimum"] - diode_tolerance
        <= vdd - row.vgs_v
        <= n1_from_m1["maximum"] + diode_tolerance
    )
    if not feasible_m3:
        raise DependentRegionError("M3 has no diode-connected feasible rows")

    n1 = _intersect(
        n1_from_m1,
        _clip_interval(
            _values_interval((vdd - row.vgs_v for row in feasible_m3), "n1 from M3"),
            vss,
            vdd,
        ),
    )
    w3 = _derived_width_interval(feasible_m3, i3, width_policy)
    w4 = dict(w3)

    feasible_m4 = tuple(
        row for row in m3_rows
        if n1["minimum"] - diode_tolerance
        <= vdd - row.vgs_v
        <= n1["maximum"] + diode_tolerance
    )
    if not feasible_m4:
        raise DependentRegionError("M4 has no gate-compatible feasible rows")

    n2 = _clip_interval(
        _values_interval((vdd - row.vds_v for row in feasible_m4), "n2"),
        vss,
        vdd,
    )

    dependent = {
        "i_m1_a": i1,
        "i_m2_a": i2,
        "i_m3_a": i3,
        "i_m4_a": i4,
        "w_m2_um": dict(w1),
        "w_m3_um": w3,
        "w_m4_um": w4,
        "w_m5_um": w5,
        "vtail_v": vtail,
        "n1_v": n1,
        "n2_v": n2,
        "vbias_v": vbias,
    }
    return {
        "group_id": "input_bias_network",
        "solver": "two_stage_input_bias_adapter",
        "status": "PASS",
        "dependent_regions": dependent,
        "technology_support": {
            "M1_rows": len(feasible_m1),
            "M3_rows": len(feasible_m3),
            "M4_rows": len(feasible_m4),
            "M5_rows": len(feasible_m5),
        },
        "physical_clipping": {
            "vtail_v": {"minimum": vss, "maximum": vin_cm},
            "n1_v": {"minimum": vss, "maximum": vdd},
            "n2_v": {"minimum": vss, "maximum": vdd},
            "vbias_v": {"minimum": vss, "maximum": vdd},
        },
    }


def _output_stage_adapter(
    model: Mapping[str, Any],
    independent: Mapping[str, Any],
    upstream: Mapping[str, Any],
    rows: Sequence[TechRow],
) -> dict[str, Any]:
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    operating = rules["operating_conditions"]
    device_rules = rules["device_constraints"]["all_mos"]
    length_um = _num(device_rules["length_um"], "length_um")
    body_limit = _num(device_rules["body_voltage_abs_max_v"], "body limit")
    width_policy = _width_policy(model)

    vdd = _num(operating["vdd_v"], "vdd_v")
    vss = _num(operating["vss_v"], "vss_v")
    vout = _domain_interval(independent["domains"]["vout_v"])
    dep = upstream["dependent_regions"]
    n2 = dep["n2_v"]
    vbias = dep["vbias_v"]
    tol = _num(
        rules["technology_intersection"]["node_voltage_tolerance_v"],
        "node voltage tolerance",
    )

    m6_rows = _filtered_rows(rows, devices["M6"], length_um=length_um, body_limit_v=body_limit)
    m7_rows = _filtered_rows(rows, devices["M7"], length_um=length_um, body_limit_v=body_limit)

    feasible_m6 = tuple(
        row for row in m6_rows
        if n2["minimum"] - tol <= vdd - row.vgs_v <= n2["maximum"] + tol
        and vout["minimum"] - tol <= vdd - row.vds_v <= vout["maximum"] + tol
    )
    feasible_m7 = tuple(
        row for row in m7_rows
        if vbias["minimum"] - tol <= vss + row.vgs_v <= vbias["maximum"] + tol
        and vout["minimum"] - tol <= vss + row.vds_v <= vout["maximum"] + tol
    )
    if not feasible_m6 or not feasible_m7:
        raise DependentRegionError(
            f"output stage has no feasible rows: M6={len(feasible_m6)}, M7={len(feasible_m7)}"
        )

    relative_tolerance = _num(
        rules["technology_intersection"]["current_relative_tolerance"],
        "current relative tolerance",
    )
    absolute_tolerance = _num(
        rules["technology_intersection"]["current_absolute_tolerance_a"],
        "current absolute tolerance",
    )

    correlated: list[dict[str, Any]] = []
    max_records = 100000

    # Build row-correlated tuples. For each row pair, choose the smallest common
    # current that yields legal total widths on both devices. The resulting tuple
    # carries all voltages, widths, and technology provenance together.
    for row6 in feasible_m6:
        n2_value = vdd - row6.vgs_v
        vout6 = vdd - row6.vds_v
        for row7 in feasible_m7:
            vbias_value = vss + row7.vgs_v
            vout7 = vss + row7.vds_v
            if abs(vout6 - vout7) > tol:
                continue

            # Unit-width-normalized current densities.
            density6 = row6.id_a / row6.width_um
            density7 = row7.id_a / row7.width_um

            current_min = max(
                density6 * width_policy["total_min_um"],
                density7 * width_policy["total_min_um"],
            )
            current_max = min(
                density6 * width_policy["total_max_um"],
                density7 * width_policy["total_max_um"],
            )
            if current_min > current_max:
                continue

            # Use both boundaries to preserve the full pair-supported current span.
            for current in (current_min, current_max):
                w6 = current / density6
                w7 = current / density7
                nf6 = _minimum_nf(w6, width_policy)
                nf7 = _minimum_nf(w7, width_policy)
                if nf6 is None or nf7 is None:
                    continue

                mismatch = abs(current - current)
                tolerance = max(
                    absolute_tolerance,
                    relative_tolerance * max(abs(current), 1e-30),
                )
                if mismatch > tolerance:
                    continue

                correlated.append(
                    {
                        "n2_v": n2_value,
                        "vbias_v": vbias_value,
                        "vout_v": 0.5 * (vout6 + vout7),
                        "i_m6_a": current,
                        "i_m7_a": current,
                        "w_m6_um": w6,
                        "w_m7_um": w7,
                        "nf_m6": nf6,
                        "nf_m7": nf7,
                        "w_finger_m6_um": w6 / nf6,
                        "w_finger_m7_um": w7 / nf7,
                        "m6_technology_row_index": row6.index,
                        "m7_technology_row_index": row7.index,
                        "m6_vgs_v": row6.vgs_v,
                        "m6_vds_v": row6.vds_v,
                        "m7_vgs_v": row7.vgs_v,
                        "m7_vds_v": row7.vds_v,
                    }
                )
                if len(correlated) >= max_records:
                    break
            if len(correlated) >= max_records:
                break
        if len(correlated) >= max_records:
            break

    if not correlated:
        raise DependentRegionError("no correlated output-stage tuples")

    dependent = {
        "i_m6_a": _values_interval((row["i_m6_a"] for row in correlated), "i_m6"),
        "i_m7_a": _values_interval((row["i_m7_a"] for row in correlated), "i_m7"),
        "w_m6_um": _values_interval((row["w_m6_um"] for row in correlated), "w_m6"),
        "w_m7_um": _values_interval((row["w_m7_um"] for row in correlated), "w_m7"),
    }

    return {
        "group_id": "output_stage",
        "solver": "two_stage_output_stage_adapter",
        "status": "PASS",
        "dependent_regions": dependent,
        "technology_support": {
            "M6_rows": len(feasible_m6),
            "M7_rows": len(feasible_m7),
        },
        "correlated_candidate_count": len(correlated),
        "correlated_candidates": correlated,
        "deferred_to_step_5": [
            "second_stage_size_relation",
            "join with correlated input_bias_network candidates",
            "complete full-circuit assignment validation",
        ],
    }


_ADAPTERS = {
    "two_stage_input_bias_adapter": _input_bias_adapter,
    "two_stage_output_stage_adapter": _output_stage_adapter,
}


def build_dependent_regions(
    compiled_model_path: Path,
    independent_regions_path: Path,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    independent = json.loads(independent_regions_path.read_text(encoding="utf-8"))
    rows = load_rows(_technology_path(model))

    groups = model["project_inputs"]["design_intent"]["assignment_synthesis"]["groups"]
    completed: dict[str, dict[str, Any]] = {}
    ordered_results = []

    for group in groups:
        group_id = str(group["id"])
        solver = str(group["solver"])
        adapter = _ADAPTERS.get(solver)
        if adapter is None:
            raise DependentRegionError(f"no adapter for {solver!r}")

        dependencies = list(group.get("depends_on", []))
        if not dependencies:
            result = adapter(model, independent, rows)
        else:
            if len(dependencies) != 1 or dependencies[0] not in completed:
                raise DependentRegionError(
                    f"group {group_id!r} has unresolved dependencies {dependencies!r}"
                )
            result = adapter(model, independent, completed[dependencies[0]], rows)

        completed[group_id] = result
        ordered_results.append(result)

    all_regions: dict[str, Any] = {}
    for result in ordered_results:
        all_regions.update(result["dependent_regions"])

    declared = {
        item["id"]
        for item in model["synthesis_interface"]["dependent_quantities"]
    }
    derived = set(all_regions)
    missing = sorted(declared - derived)
    extra = sorted(derived - declared)

    return {
        "artifact": "openams.dependent_variable_regions",
        "schema_version": 2,
        "status": "PASS" if not missing else "FAIL",
        "circuit_name": model["circuit_name"],
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "technology_source": str(_technology_path(model)),
        "groups": ordered_results,
        "dependent_regions": all_regions,
        "declared_dependent_quantities": sorted(declared),
        "derived_dependent_quantities": sorted(derived),
        "missing_declared_quantities": missing,
        "additional_derived_quantities": extra,
        "next_stage": "intersect_complete_dc_assignments",
    }


def write_dependent_regions(
    compiled_model_path: Path,
    independent_regions_path: Path,
    output_path: Path,
) -> Mapping[str, Any]:
    artifact = build_dependent_regions(
        compiled_model_path,
        independent_regions_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return artifact
