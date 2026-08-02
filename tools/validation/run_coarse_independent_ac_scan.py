#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np

from openams.synthesis.deterministic_two_stage_constructor import (
    ConstructionError,
    TwoStageConstructionPolicy,
    construct_two_stage_assignment,
)
from openams.technology.ml_continuous_oracle import (
    MlpContinuousTechnologyOracle,
)
from openams.validation.dense_capacitance_lookup import DenseCapacitanceLookup
from openams.validation.two_stage_small_signal_ac import estimate_two_stage_ac


def select_i5_values(independent_regions: Path, count: int) -> list[float]:
    artifact = json.loads(independent_regions.read_text())
    values = [
        float(value)
        for value in artifact["domains"]["i_m5_a"]["candidate_values"]
    ]
    indices = np.linspace(0, len(values) - 1, count).round().astype(int)
    return [values[index] for index in indices]


def load_existing(csv_path: Path) -> tuple[list[dict], set[int]]:
    if not csv_path.is_file():
        return [], set()
    with csv_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    completed = {int(row["grid_index"]) for row in rows}
    return rows, completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--i5-count", type=int, default=40)
    parser.add_argument("--w1-count", type=int, default=25)
    parser.add_argument("--vout-count", type=int, default=10)
    parser.add_argument("--w1-min-um", type=float, default=1.0)
    parser.add_argument("--w1-max-um", type=float, default=50.0)
    parser.add_argument("--vout-min-v", type=float, default=0.6)
    parser.add_argument("--vout-max-v", type=float, default=1.5)
    parser.add_argument("--n1-v", type=float, default=0.6)
    parser.add_argument("--vbias-v", type=float, default=0.6)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--max-points", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    generated = Path("examples/two_stage_opamp/generated")
    output_dir = generated / "assignment_synthesis/coarse_independent_ac_scan"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "coarse_scan_results.csv"
    json_path = output_dir / "coarse_scan_summary.json"
    report_path = output_dir / "COARSE_SCAN_REPORT.md"

    i5_values = select_i5_values(
        generated / "assignment_synthesis/independent_regions.json",
        args.i5_count,
    )
    w1_values = np.linspace(args.w1_min_um, args.w1_max_um, args.w1_count)
    vout_values = np.linspace(
        args.vout_min_v,
        args.vout_max_v,
        args.vout_count,
    )

    grid = [
        (index, float(i5), float(w1), float(vout))
        for index, (i5, w1, vout) in enumerate(
            (i5, w1, vout)
            for i5 in i5_values
            for w1 in w1_values
            for vout in vout_values
        )
    ]
    if args.max_points > 0:
        grid = grid[: args.max_points]

    existing_rows, completed = load_existing(csv_path) if args.resume else ([], set())
    rows = list(existing_rows)
    failures = Counter(
        row.get("failure", "")
        for row in existing_rows
        if row.get("status") != "PASS"
    )

    oracle = MlpContinuousTechnologyOracle(
        {
            "nmos": Path(os.environ["OPENAMS_MLP_NMOS"]),
            "pmos": Path(os.environ["OPENAMS_MLP_PMOS"]),
        },
        output_dir / "adaptive_mlp_points.csv",
    )
    cap_lookup = DenseCapacitanceLookup(
        Path("technology/sky130_tt_27c_mlp_dense_training_clean.csv")
    )
    frequencies = np.logspace(0.0, 10.0, 601)
    policy = TwoStageConstructionPolicy(
        n1_v=args.n1_v,
        vbias_v=args.vbias_v,
    )

    fieldnames = [
        "grid_index", "status", "failure",
        "i_m5_a", "w_m1_um", "vout_v",
        "gain_est_db", "ugb_est_hz", "phase_margin_est_deg",
        "phase_at_ugb_est_deg",
        "max_cap_lookup_distance",
        "min_saturation_margin_v",
        "vtail_v", "n1_v", "n2_v", "vbias_v",
        "w_m3_um", "w_m5_um", "w_m6_um", "w_m7_um",
        "i_m6_a", "size_relation_residual",
        "mlp_queries_cumulative",
    ]

    def save() -> None:
        with csv_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    start = time.time()
    processed_now = 0

    for grid_index, i5, w1, vout in grid:
        if grid_index in completed:
            continue

        before_queries = oracle.query_count
        try:
            assignment = construct_two_stage_assignment(
                oracle,
                i_m5_a=i5,
                w_m1_um=w1,
                vout_v=vout,
                policy=policy,
            )
            metrics = estimate_two_stage_ac(
                assignment,
                cap_lookup,
                frequencies_hz=frequencies,
            )
            margins = [
                float(point["vds_abs_v"]) - float(point["vdsat_abs_v"])
                for point in assignment["device_points"].values()
            ]
            row = {
                "grid_index": grid_index,
                "status": "PASS",
                "failure": "",
                "i_m5_a": i5,
                "w_m1_um": w1,
                "vout_v": vout,
                "gain_est_db": metrics.gain_db,
                "ugb_est_hz": metrics.ugb_hz,
                "phase_margin_est_deg": metrics.phase_margin_deg,
                "phase_at_ugb_est_deg": metrics.phase_at_ugb_deg,
                "max_cap_lookup_distance": metrics.max_cap_lookup_distance,
                "min_saturation_margin_v": min(margins),
                "vtail_v": assignment["vtail_v"],
                "n1_v": assignment["n1_v"],
                "n2_v": assignment["n2_v"],
                "vbias_v": assignment["vbias_v"],
                "w_m3_um": assignment["w_m3_um"],
                "w_m5_um": assignment["w_m5_um"],
                "w_m6_um": assignment["w_m6_um"],
                "w_m7_um": assignment["w_m7_um"],
                "i_m6_a": assignment["i_m6_a"],
                "size_relation_residual": assignment["size_relation_residual"],
                "mlp_queries_cumulative": oracle.query_count,
            }
        except (ConstructionError, ValueError, RuntimeError) as error:
            failure = str(error)
            failures[failure] += 1
            row = {
                "grid_index": grid_index,
                "status": "REJECT",
                "failure": failure,
                "i_m5_a": i5,
                "w_m1_um": w1,
                "vout_v": vout,
                "gain_est_db": "",
                "ugb_est_hz": "",
                "phase_margin_est_deg": "",
                "phase_at_ugb_est_deg": "",
                "max_cap_lookup_distance": "",
                "min_saturation_margin_v": "",
                "vtail_v": "",
                "n1_v": args.n1_v,
                "n2_v": "",
                "vbias_v": args.vbias_v,
                "w_m3_um": "",
                "w_m5_um": "",
                "w_m6_um": "",
                "w_m7_um": "",
                "i_m6_a": "",
                "size_relation_residual": "",
                "mlp_queries_cumulative": oracle.query_count,
            }

        rows.append(row)
        processed_now += 1

        if processed_now % args.checkpoint_every == 0:
            save()

        if processed_now % args.progress_every == 0:
            passed = sum(row["status"] == "PASS" for row in rows)
            elapsed = time.time() - start
            print(
                f"[PROGRESS] processed_now={processed_now} "
                f"total_rows={len(rows)}/{len(grid)} "
                f"pass={passed} reject={len(rows)-passed} "
                f"mlp_queries={oracle.query_count} "
                f"elapsed_s={elapsed:.1f}",
                flush=True,
            )

    save()

    passed_rows = [row for row in rows if row["status"] == "PASS"]
    def numeric_values(name: str) -> list[float]:
        values = []
        for row in passed_rows:
            value = row.get(name)
            if value not in ("", None):
                values.append(float(value))
        return values

    summary = {
        "status": "PASS",
        "algorithm": "deterministic_dependency_plus_dense_capacitance_ac",
        "grid": {
            "i5_count": args.i5_count,
            "w1_count": args.w1_count,
            "vout_count": args.vout_count,
            "configured_points": args.i5_count * args.w1_count * args.vout_count,
            "points_in_this_output": len(rows),
            "w1_range_um": [args.w1_min_um, args.w1_max_um],
            "vout_range_v": [args.vout_min_v, args.vout_max_v],
        },
        "construction_policy": {
            "n1_v": args.n1_v,
            "vbias_v": args.vbias_v,
        },
        "results": {
            "pass_count": len(passed_rows),
            "reject_count": len(rows) - len(passed_rows),
            "mlp_queries": oracle.query_count,
            "failure_counts": dict(failures.most_common()),
        },
        "metrics": {},
        "limitations": [
            "AC metrics are reduced small-signal estimates, not ngspice results.",
            "Capacitances use nearest-bias width-normalized dense-table values.",
            "The current MLP does not predict capacitances directly.",
            "N1 and Vbias are fixed construction-policy values.",
        ],
    }

    for name in ("gain_est_db", "ugb_est_hz", "phase_margin_est_deg"):
        values = numeric_values(name)
        summary["metrics"][name] = (
            {
                "minimum": min(values),
                "maximum": max(values),
                "mean": sum(values) / len(values),
            }
            if values
            else None
        )

    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    report_path.write_text(
        "# Coarse Independent-Variable AC Scan\n\n"
        f"- Grid: {args.i5_count} × {args.w1_count} × {args.vout_count}\n"
        f"- Rows completed: {len(rows)}\n"
        f"- Constructed assignments: {len(passed_rows)}\n"
        f"- Rejected points: {len(rows) - len(passed_rows)}\n"
        f"- MLP queries: {oracle.query_count}\n"
        f"- Policy N1: {args.n1_v} V\n"
        f"- Policy Vbias: {args.vbias_v} V\n\n"
        "AC metrics are hybrid estimates and must be validated with ngspice.\n"
    )

    print("===== OPENAMS COARSE INDEPENDENT AC SCAN =====")
    print("grid points:", len(grid))
    print("rows completed:", len(rows))
    print("constructed:", len(passed_rows))
    print("rejected:", len(rows) - len(passed_rows))
    print("MLP queries:", oracle.query_count)
    print("csv:", csv_path)
    print("json:", json_path)
    print("report:", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
