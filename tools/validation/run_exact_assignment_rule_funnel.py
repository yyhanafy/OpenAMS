#!/usr/bin/env python3
"""Exact, stage-by-stage OpenAMS assignment-rule funnel.

This script replays the production Step 5 algorithm as explicit stages and
records unique candidate counts before and after each rule. Expansion stages
are shown separately from filtering stages.

It is designed for the current two-stage-op-amp Wmax=100, NF=1 experiment and
must reproduce the production complete-assignment count exactly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from openams.synthesis.complete_assignments import (
    _device_map,
    _filtered_rows,
    _minimum_nf,
    _num,
    _technology_path,
    _width_policy,
    load_rows,
)


def close(
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


def interpolate_density(rows, target_density):
    ordered = sorted(rows, key=lambda row: row.density_a_per_um)

    for row in ordered:
        if math.isclose(
            row.density_a_per_um,
            target_density,
            rel_tol=1e-12,
            abs_tol=1e-18,
        ):
            return {
                "vgs_v": row.vgs_v,
                "lower_row_index": row.index,
                "upper_row_index": row.index,
                "fraction": 0.0,
            }

    for lower, upper in zip(ordered, ordered[1:]):
        d0 = lower.density_a_per_um
        d1 = upper.density_a_per_um
        if d0 <= target_density <= d1 and d1 > d0:
            fraction = (target_density - d0) / (d1 - d0)
            return {
                "vgs_v": lower.vgs_v
                + fraction * (upper.vgs_v - lower.vgs_v),
                "lower_row_index": lower.index,
                "upper_row_index": upper.index,
                "fraction": fraction,
            }

    return None


def record(
    funnel: list[dict[str, Any]],
    *,
    section: str,
    rule: str,
    description: str,
    before: int,
    after: int,
    operation: str = "filter",
    unique_after: int | None = None,
    notes: str = "",
) -> None:
    rejected = before - after if after <= before else 0
    funnel.append(
        {
            "section": section,
            "rule": rule,
            "description": description,
            "operation": operation,
            "before": before,
            "after": after,
            "rejected": rejected,
            "expanded_by": max(after - before, 0),
            "retained_percent": (
                100.0 * after / before if before else 0.0
            ),
            "unique_after": unique_after if unique_after is not None else after,
            "notes": notes,
        }
    )


def dedup(items: Iterable[Mapping[str, Any]], key_fn):
    result = {}
    for item in items:
        result[key_fn(item)] = item
    return list(result.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated/assignment_synthesis")
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/compiled_circuit_model.json"
        ),
    )
    parser.add_argument(
        "--independent-regions",
        type=Path,
        default=base / "independent_regions.json",
    )
    parser.add_argument(
        "--production-assignments",
        type=Path,
        default=base / "complete_assignments.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=base / "exact_rule_funnel",
    )
    args = parser.parse_args()

    model = json.loads(args.compiled_model.read_text(encoding="utf-8"))
    independent = json.loads(
        args.independent_regions.read_text(encoding="utf-8")
    )
    production = json.loads(
        args.production_assignments.read_text(encoding="utf-8")
    )
    rows = load_rows(_technology_path(model))

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
    body_limit = _num(
        all_mos["body_voltage_abs_max_v"],
        "body_voltage_abs_max_v",
    )
    node_tol = _num(
        intersection["node_voltage_tolerance_v"],
        "node_voltage_tolerance_v",
    )
    diode_tol = _num(
        intersection["diode_voltage_tolerance_v"],
        "diode_voltage_tolerance_v",
    )
    abs_i_tol = _num(
        intersection["current_absolute_tolerance_a"],
        "current_absolute_tolerance_a",
    )
    rel_i_tol = _num(
        intersection["current_relative_tolerance"],
        "current_relative_tolerance",
    )
    cap = int(intersection["max_assignments"])

    current_values = [
        _num(value, "i_m5 candidate")
        for value in independent["domains"]["i_m5_a"]["candidate_values"]
    ]
    w1_domain = independent["domains"]["w_m1_um"]
    w1_min = _num(w1_domain["technology_minimum"], "w1 minimum")
    w1_max = _num(w1_domain["technology_maximum"], "w1 maximum")

    m1_rows = _filtered_rows(
        rows, devices["M1"], length_um=length, body_limit_v=body_limit
    )
    m3_rows = _filtered_rows(
        rows, devices["M3"], length_um=length, body_limit_v=body_limit
    )
    m5_rows = _filtered_rows(
        rows, devices["M5"], length_um=length, body_limit_v=body_limit
    )
    m6_rows = _filtered_rows(
        rows, devices["M6"], length_um=length, body_limit_v=body_limit
    )
    m7_rows = _filtered_rows(
        rows, devices["M7"], length_um=length, body_limit_v=body_limit
    )
    diode_m3 = [
        row for row in m3_rows
        if abs(row.vgs_v - row.vds_v) <= diode_tol
    ]

    funnel = []

    # ---------------- INPUT-BIAS NETWORK ----------------

    candidates = [
        {"i5": i5, "i1": 0.5 * i5, "row1": row1}
        for i5 in current_values
        for row1 in m1_rows
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB00",
        description="Seed I5 candidates × saturated M1 technology rows",
        before=len(candidates),
        after=len(candidates),
        operation="seed",
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        w1 = item["i1"] / item["row1"].density_a_per_um
        nf1 = _minimum_nf(w1, policy)
        if w1_min <= w1 <= w1_max and nf1 is not None:
            next_candidates.append({**item, "w1": w1, "nf1": nf1})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB01",
        description="M1 total width, NF, and finger width are legal",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        vtail = vin - item["row1"].vgs_v
        if vss <= vtail <= vin:
            next_candidates.append({**item, "vtail": vtail})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB02",
        description="Vtail satisfies VSS ≤ Vtail ≤ Vin,CM",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        n1 = item["vtail"] + item["row1"].vds_v
        if vss <= n1 <= vdd:
            next_candidates.append({**item, "n1": n1})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB03",
        description="N1 derived from M1 lies inside the supply rails",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    expanded = []
    for item in candidates:
        for row5 in m5_rows:
            expanded.append({**item, "row5": row5})
    record(
        funnel,
        section="input_bias_network",
        rule="IB04A",
        description="Expand each partial candidate over all saturated M5 rows",
        before=before,
        after=len(expanded),
        operation="expand",
    )

    before = len(expanded)
    candidates = [
        item for item in expanded
        if abs((vss + item["row5"].vds_v) - item["vtail"]) <= node_tol
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB04B",
        description="M5 drain voltage matches Vtail",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        w5 = item["i5"] / item["row5"].density_a_per_um
        nf5 = _minimum_nf(w5, policy)
        if nf5 is not None:
            next_candidates.append(
                {
                    **item,
                    "w5": w5,
                    "nf5": nf5,
                    "vbias": vss + item["row5"].vgs_v,
                }
            )
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB05",
        description="M5 current is realizable with legal width and NF",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    expanded = [
        {**item, "row3": row3}
        for item in candidates
        for row3 in diode_m3
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB06A",
        description="Expand each partial candidate over diode-connected M3 rows",
        before=before,
        after=len(expanded),
        operation="expand",
    )

    before = len(expanded)
    candidates = [
        item for item in expanded
        if abs((vdd - item["row3"].vgs_v) - item["n1"]) <= node_tol
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB06B",
        description="M1 and diode-connected M3 agree on N1",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        w3 = item["i1"] / item["row3"].density_a_per_um
        nf3 = _minimum_nf(w3, policy)
        if nf3 is not None:
            next_candidates.append({**item, "w3": w3, "nf3": nf3})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB07",
        description="M3 current is realizable with legal width and NF",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    expanded = [
        {**item, "row4": row4}
        for item in candidates
        for row4 in m3_rows
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB08A",
        description="Expand each partial candidate over saturated M4 rows",
        before=before,
        after=len(expanded),
        operation="expand",
    )

    before = len(expanded)
    candidates = [
        item for item in expanded
        if abs(item["row4"].vgs_v - item["row3"].vgs_v) <= node_tol
    ]
    record(
        funnel,
        section="input_bias_network",
        rule="IB08B",
        description="M4 and M3 share the mirror gate voltage",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        i4 = item["row4"].density_a_per_um * item["w3"]
        if close(
            i4,
            item["i1"],
            absolute_tolerance=abs_i_tol,
            relative_tolerance=rel_i_tol,
        ):
            next_candidates.append({**item, "i4": i4})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB08C",
        description="M4 realizes I4=I2 within configured current tolerance",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    next_candidates = []
    for item in candidates:
        n2 = vdd - item["row4"].vds_v
        if vss <= n2 <= vdd:
            next_candidates.append({**item, "n2": n2})
    candidates = next_candidates
    record(
        funnel,
        section="input_bias_network",
        rule="IB08D",
        description="N2 produced by M4 lies inside the supply rails",
        before=before,
        after=len(candidates),
    )

    before = len(candidates)
    candidates = dedup(
        candidates,
        lambda item: (
            round(item["i5"], 15),
            round(item["w1"], 12),
            round(item["w3"], 12),
            round(item["w5"], 12),
            round(item["vtail"], 9),
            round(item["n1"], 9),
            round(item["n2"], 9),
            round(item["vbias"], 9),
            item["row1"].index,
            item["row3"].index,
            item["row4"].index,
            item["row5"].index,
        ),
    )
    record(
        funnel,
        section="input_bias_network",
        rule="IB09",
        description="Deduplicate identical correlated input-bias candidates",
        before=before,
        after=len(candidates),
        operation="deduplicate",
    )

    uncapped_input_count = len(candidates)
    before = len(candidates)
    candidates = candidates[:cap]
    record(
        funnel,
        section="input_bias_network",
        rule="IB10",
        description=f"Apply max_assignments cap={cap}",
        before=before,
        after=len(candidates),
        operation="cap",
        notes=(
            "If before > after, exhaustive coverage is not proven."
        ),
    )

    # ---------------- OUTPUT STAGE + FINAL JOIN ----------------

    before = len(candidates)
    expanded = [
        {"left": left, "row7": row7}
        for left in candidates
        for row7 in m7_rows
    ]
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS00",
        description="Expand each input-bias candidate over saturated M7 rows",
        before=before,
        after=len(expanded),
        operation="expand",
    )

    before = len(expanded)
    candidates_out = [
        item for item in expanded
        if abs((vss + item["row7"].vgs_v) - item["left"]["vbias"])
        <= node_tol
    ]
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS01",
        description="M7 VGS agrees with input-stage Vbias",
        before=before,
        after=len(candidates_out),
    )

    spec_vout = (
        model["project_inputs"]["specifications"]["dc_validity"]
        ["output_voltage"]
    )
    intent_vout = (
        model["project_inputs"]["design_intent"]
        ["synthesis_parameterization"]["independent_variables"]["vout_v"]
    )
    vout_min = max(
        _num(spec_vout["min"], "spec vout minimum"),
        _num(intent_vout["minimum"], "intent vout minimum"),
    )
    vout_max = min(
        _num(spec_vout["max"], "spec vout maximum"),
        _num(intent_vout["maximum"], "intent vout maximum"),
    )

    before = len(candidates_out)
    next_candidates = []
    for item in candidates_out:
        vout = vss + item["row7"].vds_v
        if vout_min <= vout <= vout_max:
            next_candidates.append({**item, "vout": vout})
    candidates_out = next_candidates
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS02",
        description="Vout satisfies design-intent and specification bounds",
        before=before,
        after=len(candidates_out),
    )

    m6_by_vds = defaultdict(list)
    for row6 in m6_rows:
        m6_by_vds[round(row6.vds_v, 9)].append(row6)

    before = len(candidates_out)
    next_candidates = []
    for item in candidates_out:
        required_vds6 = vdd - item["vout"]
        rows6 = m6_by_vds.get(round(required_vds6, 9))
        if rows6:
            next_candidates.append(
                {
                    **item,
                    "required_vds6": required_vds6,
                    "rows6": rows6,
                }
            )
    candidates_out = next_candidates
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS03",
        description="M6 has technology support at VSD=VDD−Vout",
        before=before,
        after=len(candidates_out),
    )

    before = len(candidates_out)
    next_candidates = []
    for item in candidates_out:
        left = item["left"]
        d7 = item["row7"].density_a_per_um
        target_d6 = d7 * left["w5"] / (2.0 * left["w3"])
        interp = interpolate_density(item["rows6"], target_d6)
        if interp is not None:
            next_candidates.append(
                {
                    **item,
                    "d7": d7,
                    "target_d6": target_d6,
                    "interp": interp,
                }
            )
    candidates_out = next_candidates
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS04",
        description=(
            "I6=I7 and W6/W4=2·W7/W5 yield an interpolatable M6 density"
        ),
        before=before,
        after=len(candidates_out),
    )

    before = len(candidates_out)
    next_candidates = []
    for item in candidates_out:
        n2_from_m6 = vdd - item["interp"]["vgs_v"]
        if abs(n2_from_m6 - item["left"]["n2"]) <= node_tol:
            next_candidates.append({**item, "n2_from_m6": n2_from_m6})
    candidates_out = next_candidates
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS05",
        description="Interpolated M6 VSG agrees with input-stage N2",
        before=before,
        after=len(candidates_out),
    )

    before = len(candidates_out)
    next_candidates = []
    for item in candidates_out:
        i_min = max(
            item["target_d6"] * policy["total_min_um"],
            item["d7"] * policy["total_min_um"],
        )
        i_max = min(
            item["target_d6"] * policy["total_max_um"],
            item["d7"] * policy["total_max_um"],
        )
        if i_min <= i_max:
            next_candidates.append({**item, "i_min": i_min, "i_max": i_max})
    candidates_out = next_candidates
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS06",
        description="M6 and M7 share a nonempty common-current interval",
        before=before,
        after=len(candidates_out),
    )

    before = len(candidates_out)
    expanded = []
    for item in candidates_out:
        for output_current in (item["i_min"], item["i_max"]):
            expanded.append({**item, "output_current": output_current})
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS07A",
        description="Expand each continuous output-current interval to min/max boundaries",
        before=before,
        after=len(expanded),
        operation="expand",
    )

    before = len(expanded)
    final = []
    for item in expanded:
        w6 = item["output_current"] / item["target_d6"]
        w7 = item["output_current"] / item["d7"]
        nf6 = _minimum_nf(w6, policy)
        nf7 = _minimum_nf(w7, policy)
        if nf6 is not None and nf7 is not None:
            final.append(
                {
                    **item,
                    "w6": w6,
                    "w7": w7,
                    "nf6": nf6,
                    "nf7": nf7,
                }
            )
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS07B",
        description="M6 and M7 total widths, NF, and finger widths are legal",
        before=before,
        after=len(final),
    )

    before = len(final)
    final = dedup(
        final,
        lambda item: (
            round(item["left"]["i5"], 15),
            round(item["left"]["w1"], 12),
            round(item["left"]["w3"], 12),
            round(item["left"]["w5"], 12),
            round(item["left"]["vtail"], 9),
            round(item["left"]["n1"], 9),
            round(item["left"]["n2"], 9),
            round(item["left"]["vbias"], 9),
            round(item["vout"], 9),
            round(item["output_current"], 15),
            round(item["w6"], 12),
            round(item["w7"], 12),
            item["nf6"],
            item["nf7"],
        ),
    )
    record(
        funnel,
        section="output_stage_and_final_join",
        rule="OS08",
        description="Deduplicate identical final physical assignments",
        before=before,
        after=len(final),
        operation="deduplicate",
    )

    production_count = int(production["complete_assignment_count"])
    replay_count = len(final)
    status = "PASS" if replay_count == production_count else "MISMATCH"

    report = {
        "artifact": "openams.exact_assignment_rule_funnel",
        "schema_version": 1,
        "status": status,
        "experiment": {
            "width_max_um": w1_max,
            "nf_max": policy["nf_max"],
            "independent_i5_count": len(current_values),
        },
        "coverage": {
            "uncapped_input_candidate_count": uncapped_input_count,
            "capped_input_candidate_count": min(uncapped_input_count, cap),
            "configured_cap": cap,
            "cap_reached": uncapped_input_count > cap,
        },
        "counts": {
            "production_complete_assignments": production_count,
            "replayed_complete_assignments": replay_count,
        },
        "funnel": funnel,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "exact_assignment_rule_funnel.json"
    csv_path = args.output_dir / "exact_assignment_rule_funnel.csv"
    md_path = args.output_dir / "EXACT_ASSIGNMENT_RULE_FUNNEL.md"

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "section",
                "rule",
                "description",
                "operation",
                "before",
                "after",
                "rejected",
                "expanded_by",
                "retained_percent",
                "unique_after",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(funnel)

    lines = [
        "# Exact Assignment Rule Funnel",
        "",
        f"- **Status:** {status}",
        f"- **Production assignments:** {production_count}",
        f"- **Replay assignments:** {replay_count}",
        f"- **Uncapped input candidates:** {uncapped_input_count}",
        f"- **Candidate cap:** {cap}",
        f"- **Cap reached:** {uncapped_input_count > cap}",
        "",
        "| Section | Rule | Operation | Description | Before | After | Rejected | Expanded by | Retained % |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]

    for row in funnel:
        lines.append(
            f"| {row['section']} | {row['rule']} | {row['operation']} | "
            f"{row['description']} | {row['before']} | {row['after']} | "
            f"{row['rejected']} | {row['expanded_by']} | "
            f"{row['retained_percent']:.6f}% |"
        )

    lines.extend(
        [
            "",
            "Expansion rows increase the number of combinations because a partial "
            "candidate is paired with multiple technology rows. Filter rows show "
            "the actual effect of one circuit or physical rule.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("===== OPENAMS EXACT ASSIGNMENT RULE FUNNEL =====")
    print(f"status:                    {status}")
    print(f"production assignments:    {production_count}")
    print(f"replayed assignments:      {replay_count}")
    print(f"uncapped input candidates: {uncapped_input_count}")
    print(f"configured cap:            {cap}")
    print(f"cap reached:               {uncapped_input_count > cap}")
    print()
    for row in funnel:
        print(
            f"{row['rule']:5s} {row['operation']:11s} "
            f"before={row['before']:>12d} "
            f"after={row['after']:>12d} "
            f"rejected={row['rejected']:>12d} "
            f"expanded={row['expanded_by']:>12d}"
        )
    print(f"json: {json_path}")
    print(f"csv:  {csv_path}")
    print(f"md:   {md_path}")

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
