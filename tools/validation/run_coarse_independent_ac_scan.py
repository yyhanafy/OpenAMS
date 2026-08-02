#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import csv
import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from openams.synthesis.deterministic_two_stage_constructor import (
    ConstructionError,
    TwoStageConstructionPolicy,
    construct_two_stage_assignment,
)
from openams.technology.ml_continuous_oracle import MlpContinuousTechnologyOracle
from openams.validation.dense_capacitance_lookup import DenseCapacitanceLookup
from openams.validation.two_stage_small_signal_ac import estimate_two_stage_ac

SCHEMA_VERSION = "3.0"
DEVICES = tuple(f"M{i}" for i in range(1, 8))
DEVICE_POINT_FIELDS = (
    "polarity",
    "width_um",
    "length_um",
    "vgs_abs_v",
    "vds_abs_v",
    "vbs_abs_v",
    "id_abs_a",
    "vdsat_abs_v",
    "vth_abs_v",
    "gm_s",
    "gds_s",
    "saturated",
    "in_domain",
    "source",
)
CAP_FIELDS = ("cgs_f", "cgd_f", "cdb_f", "csb_f", "distance", "source")

DEVICE_NODES = {
    "M1": ("n1", "inp", "vtail", "vss"),
    "M2": ("n2", "inn", "vtail", "vss"),
    "M3": ("n1", "n1", "vdd", "vdd"),
    "M4": ("n2", "n1", "vdd", "vdd"),
    "M5": ("vtail", "vbias", "vss", "vss"),
    "M6": ("out", "n2", "vdd", "vdd"),
    "M7": ("out", "vbias", "vss", "vss"),
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def node_voltages(assignment: dict[str, Any]) -> dict[str, float]:
    return {
        "inp": float(assignment["vin_cm_v"]),
        "inn": float(assignment["vin_cm_v"]),
        "n1": float(assignment["n1_v"]),
        "n2": float(assignment["n2_v"]),
        "out": float(assignment["vout_v"]),
        "vtail": float(assignment["vtail_v"]),
        "vbias": float(assignment["vbias_v"]),
        "vdd": float(assignment["vdd_v"]),
        "vss": float(assignment["vss_v"]),
    }


def select_i5_values(independent_regions: Path, count: int) -> list[float]:
    artifact = json.loads(independent_regions.read_text())
    values = [
        float(value)
        for value in artifact["domains"]["i_m5_a"]["candidate_values"]
    ]
    indices = np.linspace(0, len(values) - 1, count).round().astype(int)
    return [values[index] for index in indices]


def load_existing(csv_path: Path) -> tuple[list[dict[str, str]], set[int]]:
    if not csv_path.is_file():
        return [], set()
    with csv_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    completed = {int(row["grid_index"]) for row in rows}
    return rows, completed


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def make_fieldnames() -> list[str]:
    fields = [
        "schema_version",
        "grid_index",
        "assignment_id",
        "status",
        "failure_stage",
        "failure_type",
        "failure",
        "i_m5_a",
        "w_m1_um",
        "vout_v",
        "vdd_v",
        "vss_v",
        "vin_cm_v",
        "c_miller_f",
        "c_load_f",
        "n1_policy_v",
        "vbias_policy_v",
        "vtail_v",
        "n1_v",
        "n2_v",
        "vbias_v",
    ]
    fields += [f"i_m{i}_a" for i in range(1, 8)]
    fields += [f"w_m{i}_um" for i in range(1, 8)]
    fields += [
        "m2_current_residual_a",
        "size_relation_residual",
        "min_saturation_margin_v",
        "all_devices_saturated",
        "all_devices_in_domain",
        "kcl_vtail_residual_a",
        "kcl_n1_residual_a",
        "kcl_n2_residual_a",
        "kcl_out_residual_a",
        "max_kcl_residual_a",
        "max_device_current_residual_a",
        "max_device_current_relative_residual",
        "gain_est_v_v",
        "gain_est_db",
        "ugb_est_hz",
        "phase_at_ugb_unwrapped_est_deg",
        "phase_at_ugb_est_deg",
        "phase_margin_est_deg",
        "min_cap_lookup_distance",
        "max_cap_lookup_distance",
        "supply_current_est_a",
        "power_est_w",
        "gain_spec_pass",
        "ugb_spec_pass",
        "phase_margin_spec_pass",
        "power_spec_pass",
        "overall_spec_pass",
        "mlp_queries_this_point",
        "mlp_queries_cumulative",
        "constructor_runtime_ms",
        "ac_estimator_runtime_ms",
        "total_runtime_ms",
    ]
    for device in DEVICES:
        prefix = device.lower()
        fields += [f"{prefix}_{name}" for name in DEVICE_POINT_FIELDS]
        fields += [f"{prefix}_{name}" for name in CAP_FIELDS]
        fields += [
            f"{prefix}_vd_v", f"{prefix}_vg_v", f"{prefix}_vs_v", f"{prefix}_vb_v",
            f"{prefix}_vgs_signed_v", f"{prefix}_vds_signed_v", f"{prefix}_vbs_signed_v",
            f"{prefix}_vov_abs_v", f"{prefix}_gm_over_id_1_v", f"{prefix}_ro_ohm",
            f"{prefix}_target_current_a", f"{prefix}_current_residual_a",
            f"{prefix}_current_relative_residual", f"{prefix}_saturation_margin_v",
        ]
    return fields


def blank_row(fieldnames: list[str]) -> dict[str, Any]:
    return {name: "" for name in fieldnames}


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
    parser.add_argument("--vdd-v", type=float, default=1.8)
    parser.add_argument("--vss-v", type=float, default=0.0)
    parser.add_argument("--vin-cm-v", type=float, default=0.9)
    parser.add_argument("--c-miller-f", type=float, default=3e-12)
    parser.add_argument("--c-load-f", type=float, default=10e-12)
    parser.add_argument("--gain-min-db", type=float)
    parser.add_argument("--ugb-min-hz", type=float)
    parser.add_argument("--phase-margin-min-deg", type=float)
    parser.add_argument("--power-max-w", type=float)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--max-points", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "coarse_independent_ac_scan_v2"
        ),
    )
    args = parser.parse_args()

    generated = Path("examples/two_stage_opamp/generated")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "coarse_scan_results.csv"
    json_path = output_dir / "coarse_scan_summary.json"
    report_path = output_dir / "COARSE_SCAN_REPORT.md"
    config_path = output_dir / "run_configuration.json"
    adaptive_path = output_dir / "adaptive_mlp_points.csv"
    assignments_path = output_dir / "constructed_assignments.jsonl"

    if csv_path.exists() and not args.resume:
        raise SystemExit(
            f"refusing to overwrite existing output: {csv_path}; "
            "choose a new --output-dir or use --resume"
        )

    i5_values = select_i5_values(
        generated / "assignment_synthesis/independent_regions.json",
        args.i5_count,
    )
    w1_values = np.linspace(args.w1_min_um, args.w1_max_um, args.w1_count)
    vout_values = np.linspace(args.vout_min_v, args.vout_max_v, args.vout_count)

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
    rows: list[dict[str, Any]] = list(existing_rows)
    assignment_records: list[dict[str, Any]] = []
    if args.resume and assignments_path.is_file():
        assignment_records = [json.loads(line) for line in assignments_path.read_text().splitlines() if line.strip()]
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
        adaptive_path,
    )
    dense_table_path = Path(
        "technology/sky130_tt_27c_mlp_dense_training_clean.csv"
    )
    cap_lookup = DenseCapacitanceLookup(dense_table_path)
    frequencies = np.logspace(0.0, 10.0, 601)
    policy = TwoStageConstructionPolicy(n1_v=args.n1_v, vbias_v=args.vbias_v)
    fieldnames = make_fieldnames()

    config = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "deterministic_dependency_plus_dense_capacitance_ac",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, *sys.argv],
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_status_porcelain": git_value("status", "--porcelain"),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "processor": platform.processor(),
        "grid": {
            "i5_count": args.i5_count,
            "w1_count": args.w1_count,
            "vout_count": args.vout_count,
            "w1_range_um": [args.w1_min_um, args.w1_max_um],
            "vout_range_v": [args.vout_min_v, args.vout_max_v],
        },
        "construction_policy": vars(policy),
        "operating_conditions": {
            "vdd_v": args.vdd_v,
            "vss_v": args.vss_v,
            "vin_cm_v": args.vin_cm_v,
            "c_miller_f": args.c_miller_f,
            "c_load_f": args.c_load_f,
        },
        "models": {
            "nmos_checkpoint": os.environ["OPENAMS_MLP_NMOS"],
            "nmos_checkpoint_sha256": sha256_file(Path(os.environ["OPENAMS_MLP_NMOS"])),
            "pmos_checkpoint": os.environ["OPENAMS_MLP_PMOS"],
            "pmos_checkpoint_sha256": sha256_file(Path(os.environ["OPENAMS_MLP_PMOS"])),
            "dense_capacitance_table": str(dense_table_path),
            "dense_capacitance_table_sha256": sha256_file(dense_table_path),
            "mlp_outputs": ["id_abs_a", "vdsat_abs_v", "vth_abs_v", "gm_s", "gds_s"],
            "not_available_from_current_mlp": ["gmb_s", "intrinsic_capacitances"],
        },
        "specification_thresholds": {
            "gain_min_db": args.gain_min_db,
            "ugb_min_hz": args.ugb_min_hz,
            "phase_margin_min_deg": args.phase_margin_min_deg,
            "power_max_w": args.power_max_w,
        },
        "terminal_voltage_convention": {
            "vd_v_vg_v_vs_v_vb_v": "signed node voltages relative to VSS=0 reference",
            "vgs_signed_v": "Vg-Vs",
            "vds_signed_v": "Vd-Vs",
            "vbs_signed_v": "Vb-Vs",
            "*_abs_v": "polarity-normalized nonnegative magnitudes supplied to MLP",
        },
        "frequency_sweep": {
            "minimum_hz": float(frequencies[0]),
            "maximum_hz": float(frequencies[-1]),
            "count": len(frequencies),
        },
    }
    config_path.write_text(json.dumps(config, indent=2, default=str) + "\n")

    def save() -> None:
        with csv_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        with assignments_path.open("w", encoding="utf-8") as stream:
            for record in assignment_records:
                stream.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    start = time.perf_counter()
    processed_now = 0

    for grid_index, i5, w1, vout in grid:
        if grid_index in completed:
            continue

        point_start = time.perf_counter()
        before_queries = oracle.query_count
        constructor_ms = 0.0
        ac_ms = 0.0
        row = blank_row(fieldnames)
        row.update(
            {
                "schema_version": SCHEMA_VERSION,
                "grid_index": grid_index,
                "status": "REJECT",
                "failure_stage": "construction",
                "i_m5_a": i5,
                "w_m1_um": w1,
                "vout_v": vout,
                "vdd_v": args.vdd_v,
                "vss_v": args.vss_v,
                "vin_cm_v": args.vin_cm_v,
                "c_miller_f": args.c_miller_f,
                "c_load_f": args.c_load_f,
                "n1_policy_v": args.n1_v,
                "vbias_policy_v": args.vbias_v,
            }
        )

        try:
            constructor_start = time.perf_counter()
            assignment = construct_two_stage_assignment(
                oracle,
                i_m5_a=i5,
                w_m1_um=w1,
                vout_v=vout,
                policy=policy,
                vdd_v=args.vdd_v,
                vss_v=args.vss_v,
                vin_cm_v=args.vin_cm_v,
            )
            constructor_ms = (time.perf_counter() - constructor_start) * 1000.0

            ac_start = time.perf_counter()
            metrics = estimate_two_stage_ac(
                assignment,
                cap_lookup,
                frequencies_hz=frequencies,
                c_miller_f=args.c_miller_f,
                c_load_f=args.c_load_f,
            )
            ac_ms = (time.perf_counter() - ac_start) * 1000.0

            points = assignment["device_points"]
            margins = {
                device: float(point["vds_abs_v"]) - float(point["vdsat_abs_v"])
                for device, point in points.items()
            }
            supply_current = float(assignment["i_m3_a"]) + float(
                assignment["i_m4_a"]
            ) + float(assignment["i_m6_a"])
            nodes = node_voltages(assignment)
            target_currents = {device: float(assignment[f"i_{device.lower()}_a"]) for device in DEVICES}
            current_residuals = {
                device: float(points[device]["id_abs_a"]) - target_currents[device]
                for device in DEVICES
            }
            current_relative_residuals = {
                device: abs(current_residuals[device]) / max(abs(target_currents[device]), 1e-30)
                for device in DEVICES
            }
            kcl = {
                "vtail": float(assignment["i_m5_a"]) - float(assignment["i_m1_a"]) - float(assignment["i_m2_a"]),
                "n1": float(assignment["i_m3_a"]) - float(assignment["i_m1_a"]),
                "n2": float(assignment["i_m4_a"]) - float(assignment["i_m2_a"]),
                "out": float(assignment["i_m6_a"]) - float(assignment["i_m7_a"]),
            }

            row.update(
                {
                    "assignment_id": f"deterministic_dependency_assignment_{grid_index:06d}",
                    "status": "PASS",
                    "failure_stage": "",
                    "failure_type": "",
                    "failure": "",
                    "vtail_v": assignment["vtail_v"],
                    "n1_v": assignment["n1_v"],
                    "n2_v": assignment["n2_v"],
                    "vbias_v": assignment["vbias_v"],
                    "m2_current_residual_a": assignment["m2_current_residual_a"],
                    "size_relation_residual": assignment["size_relation_residual"],
                    "min_saturation_margin_v": min(margins.values()),
                    "all_devices_saturated": all(
                        bool(point["saturated"]) for point in points.values()
                    ),
                    "all_devices_in_domain": all(
                        bool(point["in_domain"]) for point in points.values()
                    ),
                    "kcl_vtail_residual_a": kcl["vtail"],
                    "kcl_n1_residual_a": kcl["n1"],
                    "kcl_n2_residual_a": kcl["n2"],
                    "kcl_out_residual_a": kcl["out"],
                    "max_kcl_residual_a": max(abs(value) for value in kcl.values()),
                    "max_device_current_residual_a": max(abs(value) for value in current_residuals.values()),
                    "max_device_current_relative_residual": max(current_relative_residuals.values()),
                    "gain_est_v_v": metrics.gain_v_v,
                    "gain_est_db": metrics.gain_db,
                    "ugb_est_hz": metrics.ugb_hz,
                    "phase_at_ugb_unwrapped_est_deg": (
                        metrics.phase_at_ugb_unwrapped_deg
                    ),
                    "phase_at_ugb_est_deg": metrics.phase_at_ugb_deg,
                    "phase_margin_est_deg": metrics.phase_margin_deg,
                    "min_cap_lookup_distance": metrics.min_cap_lookup_distance,
                    "max_cap_lookup_distance": metrics.max_cap_lookup_distance,
                    "supply_current_est_a": supply_current,
                    "power_est_w": (args.vdd_v - args.vss_v) * supply_current,
                }
            )
            row["gain_spec_pass"] = (
                "" if args.gain_min_db is None or metrics.gain_db is None
                else metrics.gain_db >= args.gain_min_db
            )
            row["ugb_spec_pass"] = (
                "" if args.ugb_min_hz is None or metrics.ugb_hz is None
                else metrics.ugb_hz >= args.ugb_min_hz
            )
            row["phase_margin_spec_pass"] = (
                ""
                if args.phase_margin_min_deg is None or metrics.phase_margin_deg is None
                else metrics.phase_margin_deg >= args.phase_margin_min_deg
            )
            row["power_spec_pass"] = (
                "" if args.power_max_w is None
                else row["power_est_w"] <= args.power_max_w
            )
            flags = [
                row[name]
                for name in (
                    "gain_spec_pass",
                    "ugb_spec_pass",
                    "phase_margin_spec_pass",
                    "power_spec_pass",
                )
                if row[name] != ""
            ]
            row["overall_spec_pass"] = "" if not flags else all(flags)

            for index in range(1, 8):
                row[f"i_m{index}_a"] = assignment[f"i_m{index}_a"]
                row[f"w_m{index}_um"] = assignment[f"w_m{index}_um"]

            device_records: dict[str, Any] = {}
            for device in DEVICES:
                prefix = device.lower()
                point = points[device]
                for name in DEVICE_POINT_FIELDS:
                    row[f"{prefix}_{name}"] = point[name]
                cap = metrics.device_capacitances[device]
                for name in CAP_FIELDS:
                    row[f"{prefix}_{name}"] = getattr(cap, name)

                drain, gate, source, body = DEVICE_NODES[device]
                vd, vg, vs, vb = (nodes[drain], nodes[gate], nodes[source], nodes[body])
                id_abs = float(point["id_abs_a"])
                gm = float(point["gm_s"])
                gds = float(point["gds_s"])
                extras = {
                    "vd_v": vd,
                    "vg_v": vg,
                    "vs_v": vs,
                    "vb_v": vb,
                    "vgs_signed_v": vg - vs,
                    "vds_signed_v": vd - vs,
                    "vbs_signed_v": vb - vs,
                    "vov_abs_v": float(point["vgs_abs_v"]) - float(point["vth_abs_v"]),
                    "gm_over_id_1_v": gm / max(id_abs, 1e-30),
                    "ro_ohm": float("inf") if gds <= 0.0 else 1.0 / gds,
                    "target_current_a": target_currents[device],
                    "current_residual_a": current_residuals[device],
                    "current_relative_residual": current_relative_residuals[device],
                    "saturation_margin_v": margins[device],
                }
                for name, value in extras.items():
                    row[f"{prefix}_{name}"] = value
                device_records[device] = {
                    "nodes": {"drain": drain, "gate": gate, "source": source, "body": body},
                    "model_point": dict(point),
                    "capacitances": {name: getattr(cap, name) for name in CAP_FIELDS},
                    "derived": extras,
                }

            assignment_records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "grid_index": grid_index,
                    "assignment_id": row["assignment_id"],
                    "independent_variables": {
                        "i_m5_a": i5,
                        "w_m1_um": w1,
                        "vout_v": vout,
                    },
                    "assignment": assignment,
                    "device_records": device_records,
                    "ac_metrics": {
                        "gain_est_v_v": metrics.gain_v_v,
                        "gain_est_db": metrics.gain_db,
                        "ugb_est_hz": metrics.ugb_hz,
                        "phase_at_ugb_unwrapped_est_deg": metrics.phase_at_ugb_unwrapped_deg,
                        "phase_at_ugb_est_deg": metrics.phase_at_ugb_deg,
                        "phase_margin_est_deg": metrics.phase_margin_deg,
                    },
                    "diagnostics": {
                        "kcl_residuals_a": kcl,
                        "max_kcl_residual_a": row["max_kcl_residual_a"],
                        "max_device_current_residual_a": row["max_device_current_residual_a"],
                        "max_device_current_relative_residual": row["max_device_current_relative_residual"],
                    },
                }
            )

        except (ConstructionError, ValueError, RuntimeError) as error:
            failure = str(error)
            failures[failure] += 1
            row["failure_type"] = type(error).__name__
            row["failure"] = failure
            row["n1_v"] = args.n1_v
            row["vbias_v"] = args.vbias_v

        row["mlp_queries_this_point"] = oracle.query_count - before_queries
        row["mlp_queries_cumulative"] = oracle.query_count
        row["constructor_runtime_ms"] = constructor_ms
        row["ac_estimator_runtime_ms"] = ac_ms
        row["total_runtime_ms"] = (time.perf_counter() - point_start) * 1000.0
        rows.append(row)
        processed_now += 1

        if processed_now % args.checkpoint_every == 0:
            save()

        if processed_now % args.progress_every == 0:
            passed = sum(row["status"] == "PASS" for row in rows)
            elapsed = time.perf_counter() - start
            print(
                f"[PROGRESS] processed_now={processed_now} "
                f"total_rows={len(rows)}/{len(grid)} "
                f"pass={passed} reject={len(rows)-passed} "
                f"mlp_queries={oracle.query_count} elapsed_s={elapsed:.1f}",
                flush=True,
            )

    save()

    passed_rows = [row for row in rows if row["status"] == "PASS"]

    def numeric_values(name: str) -> list[float]:
        return [
            float(row[name])
            for row in passed_rows
            if row.get(name) not in ("", None)
        ]

    summary: dict[str, Any] = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
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
        "construction_policy": {"n1_v": args.n1_v, "vbias_v": args.vbias_v},
        "results": {
            "pass_count": len(passed_rows),
            "reject_count": len(rows) - len(passed_rows),
            "mlp_queries": oracle.query_count,
            "failure_counts": dict(failures.most_common()),
        },
        "metrics": {},
        "validation": {
            "row_count_matches_grid": len(rows) == len(grid),
            "unique_grid_indices": len({int(row["grid_index"]) for row in rows}),
            "phase_at_ugb_principal_range": all(
                -180.0 <= float(row["phase_at_ugb_est_deg"]) < 180.0
                for row in passed_rows
                if row.get("phase_at_ugb_est_deg") not in ("", None)
            ),
        },
        "limitations": [
            "AC metrics are reduced small-signal estimates, not ngspice results.",
            "Capacitances use nearest-bias width-normalized dense-table values.",
            "The current MLP does not predict capacitances directly.",
            "N1 and Vbias are fixed construction-policy values.",
        ],
    }

    for name in (
        "gain_est_db",
        "ugb_est_hz",
        "phase_margin_est_deg",
        "power_est_w",
    ):
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
        f"- Schema: {SCHEMA_VERSION}\n"
        f"- Grid: {args.i5_count} × {args.w1_count} × {args.vout_count}\n"
        f"- Rows completed: {len(rows)}\n"
        f"- Constructed assignments: {len(passed_rows)}\n"
        f"- Rejected points: {len(rows) - len(passed_rows)}\n"
        f"- MLP queries: {oracle.query_count}\n"
        f"- Policy N1: {args.n1_v} V\n"
        f"- Policy Vbias: {args.vbias_v} V\n\n"
        "Phase margin uses the principal phase at unity gain.\n\n"
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
    print("configuration:", config_path)
    print("assignments:", assignments_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
